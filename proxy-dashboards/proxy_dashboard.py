import argparse
from pyzabbix import ZabbixAPI, ZabbixAPIException
from requests import Session
from enum import Enum
from semantic_version import Version
import urllib3
import logging


logging.captureWarnings(True)
logger = logging.getLogger(__name__)


VERSION_SUPPORTING_TOKENS = Version('5.4.0')
VERSION_SUPPORTING_PAGES = Version('5.4.0')


class CretaionMode(str, Enum):
    PAGED = 'paged'
    SINGLE = 'single'


def make_zabbix_session(args: argparse.Namespace) -> ZabbixAPI:
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


def select_creation_mode(mode: str, zabbix_version: Version) -> CretaionMode:
    creation_mode = CretaionMode(mode)
    if creation_mode is CretaionMode.PAGED and zabbix_version < VERSION_SUPPORTING_PAGES:
        raise RuntimeError("This version doesn't support paged dashboards!")
    return creation_mode


def parse_args() -> argparse.Namespace:
    from argparse import ArgumentParser
    from pathlib import Path
    parser = ArgumentParser(Path(__file__).name, description="generate proxies yo", epilog="Copyright Robert Szulist")
    parser.add_argument('-z', '--zabbix-api', help="Zabbix API URL", default="http:/localhost", required=True)
    parser.add_argument('-u', '--username', help="Zabbix user")
    parser.add_argument('-p', '--password', help="Zabbix user password")
    parser.add_argument('-t', '--token', help="Zabbix API token")
    parser.add_argument('-g', '--proxy-group',  help="Name of hostgroup containing proxies", required=True)
    parser.add_argument(
        '-m', '--creation-mode',
        help="Create a single dashboard with page per proxy or multiple dashboards (dashboard per proxy)", 
        choices=[mode.value for mode in CretaionMode.__members__.values()],
        default=CretaionMode.PAGED.value
    )
    parser.add_argument('-k', '--no-verify-ssl', help="Verify SSL certificate", action='store_true')
    return parser.parse_args()


def main():
    args = parse_args()

    try:
        zapi = make_zabbix_session(args)
        creation_mode = select_creation_mode(args.creation_mode, zapi.version)
    except RuntimeError as e:
        logger.critical(f"Operation failed due do unexpected Zabbix version: {e}")
        exit(1)

    proxies = get_proxies(zapi, 'Zabbix proxies')

    dashboards = []
    if creation_mode is CretaionMode.PAGED:
        dashboard = generate_dashboard("Zabbix proxies health")
        dashboard['pages'] = [generate_dashboard_page(proxy) for proxy in proxies]
        dashboards.append(dashboard)
    elif creation_mode is CretaionMode.SINGLE:
        for proxy in proxies:
            dashboard = generate_dashboard(f"Zabbix proxy health: {proxy['name']}")
            dashboard_page = generate_dashboard_page(proxy)
            if zapi.version >= VERSION_SUPPORTING_PAGES:
                dashboard['pages'].append(dashboard_page)
            else:
                dashboard['widgets'] = dashboard_page['widgets']
            dashboards.append(dashboard)

    for dashboard in dashboards:
        try:
            zapi.dashboard.create(dashboard)
        except ZabbixAPIException as e:
            logger.error(e.error)

    if zapi.is_authenticated and not zapi.use_api_token:
        zapi.user.logout()


def get_proxies(zapi: ZabbixAPI, proxy_group) -> list:
    proxies = zapi.hostgroup.get(filter={'name': proxy_group}, selectHosts=['name', 'hostid'])[0]
    return [proxy for proxy in proxies['hosts']]


def generate_dashboard(dashboard_name: str):
    return {
        "name": f"{dashboard_name}",
        "userid": "1",
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
