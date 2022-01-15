from argparse import ArgumentParser, Namespace
from pathlib import Path
import typing
from pyzabbix import ZabbixAPI, ZabbixAPIException
from requests import Session
from enum import Enum
from semantic_version import Version
import urllib3
import logging
import sys
from typing import Optional


logger = logging.getLogger(__name__)


VERSION_SUPPORTING_TOKENS = Version('5.4.0')
VERSION_SUPPORTING_PAGES = Version('5.4.0')


class CretaionMode(str, Enum):
    PAGED = 'paged'
    SINGLE = 'single'


def make_zabbix_session(args: Namespace) -> ZabbixAPI:
    s = Session()
    if args.no_verify_ssl:
        s.verify = False
        urllib3.disable_warnings()
    zapi = ZabbixAPI(args.zabbix_api, session=s)
    if args.username and args.password:
        zapi.login(args.username, args.password)
    elif args.token:
        zabbix_version = Version(zapi.api_version())
        if zabbix_version < VERSION_SUPPORTING_TOKENS:
            raise RuntimeError("This version doesn't support API tokens!")
        zapi.login(api_token=args.token)
    return zapi


def get_user_id(zapi: ZabbixAPI) -> str:
    user = None
    if zapi.use_api_token:
        user = zapi.token.get(token=zapi.auth)[0]['userid']
    else:
        user = zapi.check_authentication()['userid']
    return user


def select_creation_mode(mode: str, zabbix_version: Version) -> CretaionMode:
    creation_mode = CretaionMode(mode)
    if creation_mode is CretaionMode.PAGED and zabbix_version < VERSION_SUPPORTING_PAGES:
        raise RuntimeError("This version doesn't support paged dashboards!")
    return creation_mode


def parse_args() -> Namespace:
    parser = ArgumentParser(
        Path(__file__).name,
        description="This script will generate performance dashboards for all proxies contained in the specified group.",
        epilog="Copyright Robert Szulist"
    )

    zabbix_group = parser.add_argument_group('Zabbix connection')
    zabbix_group.add_argument('-z', '--zabbix-api', help="Zabbix API URL", default="http:/localhost", required=True)
    zabbix_group.add_argument('-u', '--username', help="Zabbix user")
    zabbix_group.add_argument('-p', '--password', help="Zabbix user password")
    zabbix_group.add_argument('-t', '--token', help="Zabbix API token")
    zabbix_group.add_argument('-g', '--proxy-group',  help="Name of hostgroup containing proxies", required=True)

    creation = parser.add_argument_group('Dashboard creation options')
    creation.add_argument(
        '-m', '--creation-mode',
        help="Create a single dashboard with page per proxy or multiple dashboards (dashboard per proxy)",
        choices=[mode.value for mode in CretaionMode.__members__.values()],
        default=CretaionMode.PAGED.value
    )
    creation.add_argument('-f', '--force', help="Force update if dashboard already exists", action='store_true')

    logs = parser.add_argument_group('Logging')
    logs.add_argument('-o', '--output', help="Where to write log output", choices=('stdout', 'file'), default='stdout')
    logs.add_argument('-F', '--file', help="Log file path. Required if output is `file`")
    logs.add_argument('-l', '--level', help="Logger log level", choices=('debug', 'info', 'warning', 'error'), default='info')

    other = parser.add_argument_group('Other')
    other.add_argument('-k', '--no-verify-ssl', help="Verify SSL certificate", action='store_true')
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    logging.captureWarnings(True)
    numeric_level = getattr(logging, args.level.upper(), None)
    if args.output == 'file':
        filename = Path(args.file)
        logging.basicConfig(filename=filename, level=numeric_level)
    else:
        logging.basicConfig(stream=sys.stdout, level=numeric_level)

    logger.info("Starting the creation of dashboards")

    try:
        zapi = make_zabbix_session(args)
        creation_mode = select_creation_mode(args.creation_mode, zapi.version)
    except RuntimeError as e:
        logger.critical(f"Operation failed due do unexpected Zabbix version: {e}")
        exit(1)

    proxies = get_proxies(zapi, args.proxy_group)
    if proxies is None:
        exit(2)
    elif not proxies:
        logger.warning(f"Host group '{args.proxy_group}' is empty")

    dashboards = []
    owner = get_user_id(zapi)
    if creation_mode is CretaionMode.PAGED:
        dashboard = generate_dashboard("Zabbix proxies health", owner)
        dashboard['pages'] = [generate_dashboard_page(proxy) for proxy in proxies]
        dashboards.append(dashboard)
    elif creation_mode is CretaionMode.SINGLE:
        for proxy in proxies:
            dashboard = generate_dashboard(f"Zabbix proxy health: {proxy['name']}", owner)
            dashboard_page = generate_dashboard_page(proxy)
            if zapi.version >= VERSION_SUPPORTING_PAGES:
                dashboard['pages'].append(dashboard_page)
            else:
                dashboard['widgets'] = dashboard_page['widgets']
                del dashboard['pages']
            dashboards.append(dashboard)

    for dashboard in dashboards:
        d_name = dashboard['name']
        try:
            zapi.dashboard.create(dashboard)
            logger.info(f"Created: {d_name}")
        except ZabbixAPIException as e:
            if args.force:
                logger.info(f"Forcing update of {d_name}")

                existing_dashboard = zapi.dashboard.get(filter={'name': d_name}, output=['dashboardid'])
                d_id = existing_dashboard[0]['dashboardid']
                if zapi.version >= VERSION_SUPPORTING_PAGES:
                    zapi.dashboard.update(dashboardid=d_id, pages=dashboard['pages'])
                else:
                    zapi.dashboard.update(dashboardid=d_id, widgets=dashboard['widgets'])
                logger.info(f"Updated: {d_name}")
            else:
                logger.error(e.error['data'])

    if zapi.is_authenticated and not zapi.use_api_token:
        zapi.user.logout()


def get_proxies(zapi: ZabbixAPI, proxy_group: str) -> Optional[list]:
    try:
        proxies = zapi.hostgroup.get(filter={'name': proxy_group}, selectHosts=['name', 'hostid'])[0]
    except IndexError:
        logger.error(f"Host group '{proxy_group}' doesn't exist!")
        return
    return [proxy for proxy in proxies['hosts']]


def generate_dashboard(dashboard_name: str, owner_id: str) -> dict:
    return {
        "name": f"{dashboard_name}",
        "userid": owner_id,
        "private": "1",
        "display_period": "30",
        "auto_start": "1",
        "pages": []
    }


def generate_dashboard_page(proxy: dict) -> dict:
    proxy_name = proxy['name']
    proxy_id = proxy['hostid']
    return {
        "name": f"{proxy_name}",
        "display_period": "0",
        "widgets": [{
            "type": "svggraph",
            "name": "Queue size",
            "x": "16",
            "y": "5",
            "width": "8",
            "height": "5",
            "view_mode": "0",
            "fields": [
                {"type": "1", "name": "ds.hosts.0.0", "value": f"{proxy_name}"},
                {"type": "1", "name": "ds.items.0.0", "value": "Zabbix queue"},
                {"type": "1", "name": "ds.color.0", "value": "B0AF07"},
                {"type": "1", "name": "ds.hosts.1.0", "value": f"{proxy_name}"},
                {"type": "1", "name": "ds.items.1.0","value": "Zabbix queue over 10 minutes"},
                {"type": "1", "name": "ds.color.1", "value": "E53935"},
                {"type": "1", "name": "ds.hosts.2.0", "value": f"{proxy_name}"},
                {"type": "1", "name": "ds.items.2.0", "value": "Zabbix preprocessing queue"},
                {"type": "1", "name": "ds.color.2", "value": "0275B8"},
                {"type": "1", "name": "lefty_min", "value": "0"},
                {"type": "1", "name": "problemhosts.0", "value": f"{proxy_name}"},
                {"type": "0", "name": "ds.width.0", "value": "2"},
                {"type": "0", "name": "ds.transparency.0", "value": "0"},
                {"type": "0", "name": "ds.fill.0", "value": "0"},
                {"type": "0", "name": "ds.width.1", "value": "2"},
                {"type": "0", "name": "ds.transparency.1", "value": "0"},
                {"type": "0", "name": "ds.fill.1", "value": "0"},
                {"type": "0", "name": "ds.width.2", "value": "2"},
                {"type": "0", "name": "ds.transparency.2", "value": "0"},
                {"type": "0", "name": "ds.fill.2", "value": "0"},
                {"type": "0", "name": "righty", "value": "0"},
                {"type": "0", "name": "legend", "value": "0"},
                {"type": "0", "name": "show_problems", "value": "1"},
                {"type": "0", "name": "graph_item_problems", "value": "0"}
            ]
        },
        {
            "type": "svggraph",
            "name": "Values processed per second",
            "x": "8",
            "y": "0",
            "width": "8",
            "height": "5",
            "view_mode": "0",
            "fields": [
                {"type": "1", "name": "ds.hosts.0.0", "value": f"{proxy_name}"},
                {"type": "1", "name": "ds.items.0.0", "value": "Number of processed *values per second"},
                {"type": "1", "name": "ds.color.0", "value": "00BFFF"},
                {"type": "1", "name": "lefty_min", "value": "0"},
                {"type": "1", "name": "problemhosts.0", "value": f"{proxy_name}"},
                {"type": "0", "name": "ds.transparency.0", "value": "0"},
                {"type": "0", "name": "righty", "value": "0"},
                {"type": "0", "name": "legend", "value": "0"},
                {"type": "0", "name": "show_problems", "value": "1"},
                {"type": "0", "name": "graph_item_problems", "value": "0"}
            ]
        },
        {
            "type": "svggraph",
            "name": "Utilization of data collectors",
            "x": "0",
            "y": "5",
            "width": "8",
            "height": "5",
            "view_mode": "0",
            "fields": [
                {"type": "1", "name": "ds.hosts.0.0", "value": f"{proxy_name}"},
                {"type": "1", "name": "ds.items.0.0", "value": "Utilization of * data collector *"},
                {"type": "1", "name": "ds.color.0", "value": "E57373"},
                {"type": "1", "name": "lefty_min", "value": "0"},
                {"type": "1", "name": "lefty_max", "value": "100"},
                {"type": "1", "name": "problemhosts.0", "value": f"{proxy_name}"},
                {"type": "0", "name": "ds.transparency.0", "value": "0"},
                {"type": "0", "name": "righty", "value": "0"},
                {"type": "0", "name": "legend", "value": "0"},
                {"type": "0", "name": "show_problems", "value": "1"},
                {"type": "0", "name": "graph_item_problems", "value": "0"}
            ]
        },
        {
            "type": "svggraph",
            "name": "Utilization of internal processes",
            "x": "8",
            "y": "5",
            "width": "8",
            "height": "5",
            "view_mode": "0",
            "fields": [
                {"type": "1", "name": "ds.hosts.0.0", "value": f"{proxy_name}"},
                {"type": "1", "name": "ds.items.0.0", "value": "Utilization of * internal *"},
                {"type": "1", "name": "ds.color.0", "value": "E57373"},
                {"type": "1", "name": "lefty_min", "value": "0"},
                {"type": "1", "name": "lefty_max", "value": "100"},
                {"type": "1", "name": "problemhosts.0", "value": f"{proxy_name}"},
                {"type": "0", "name": "ds.transparency.0", "value": "0"},
                {"type": "0", "name": "righty", "value": "0"},
                {"type": "0", "name": "legend", "value": "0"},
                {"type": "0", "name": "show_problems", "value": "1"},
                {"type": "0", "name": "graph_item_problems", "value": "0"}
            ]
        },
        {
            "type": "svggraph",
            "name": "Cache usage",
            "x": "16",
            "y": "0",
            "width": "8",
            "height": "5",
            "view_mode": "0",
            "fields": [
                {"type": "1", "name": "ds.hosts.0.0", "value": f"{proxy_name}"},
                {"type": "1", "name": "ds.items.0.0", "value": r"Zabbix*cache*% used"},
                {"type": "1", "name": "ds.color.0", "value": "4DB6AC"},
                {"type": "1", "name": "lefty_min", "value": "0"},
                {"type": "1", "name": "lefty_max", "value": "100"},
                {"type": "1", "name": "problemhosts.0", "value": f"{proxy_name}"},
                {"type": "0", "name": "ds.width.0", "value": "2"},
                {"type": "0", "name": "ds.transparency.0", "value": "0"},
                {"type": "0", "name": "ds.fill.0", "value": "0"},
                {"type": "0", "name": "righty", "value": "0"},
                {"type": "0", "name": "legend", "value": "0"},
                {"type": "0", "name": "show_problems", "value": "1"},
                {"type": "0", "name": "graph_item_problems", "value": "0"}
            ]
        },
        {
            "type": "problems",
            "name": "",
            "x": "0",
            "y": "0",
            "width": "8",
            "height": "5",
            "view_mode": "0",
            "fields": [
                {"type": "3", "name": "hostids", "value": f"{proxy_id}"},
                {"type": "0", "name": "show_opdata", "value": "1"}
            ]
       }]
   }


if __name__ == "__main__":
    main()
