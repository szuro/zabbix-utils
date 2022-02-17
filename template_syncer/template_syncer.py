import requests
from pyzabbix import ZabbixAPI, ZabbixAPIException
import yaml
import semantic_version
import urllib3
urllib3.disable_warnings()


def load_config(config_file: str) -> dict:
    with open(config_file, 'r') as f:
        config = yaml.load(f, Loader=yaml.FullLoader)
    return config


def get_upstream_template(url: str) -> str:
    template = requests.get(url)
    return template.text


def upload_template(zapi: ZabbixAPI, template: str, format: str):
    rules={
        'discoveryRules': {
            "createMissing": True,
            "updateExisting": True
        },
        'graphs': {
            "createMissing": True,
            "updateExisting": True
        },
        'groups': {
            "createMissing": True,
            "updateExisting": True
        },
        'httptests': {
            "createMissing": True,
            "updateExisting": True
        },
        'items': {
            "createMissing": True,
            "updateExisting": True
        },
        'templateLinkage': {
            "createMissing": True,
        },
        'templates': {
            "createMissing": True,
            "updateExisting": True
        },
        'templateDashboards': {
            "createMissing": True,
            "updateExisting": True
        },
        'triggers': {
            "createMissing": True,
            "updateExisting": True
        }
    }
    if zapi.version >= semantic_version.Version('5.4.0'):
        rules['valueMaps'] = {
                "createMissing": True,
                "updateExisting": True
            }
    try:
        zapi.confimport(
            confformat=format,
            rules=rules,
            source=template,
        )
    except ZabbixAPIException:
        print("Zabbix upload failed")


def infer_type(url: str) -> str:
    lower_url = url.lower()
    if lower_url.endswith('yaml') or lower_url.endswith('yml'):
        return 'yaml'
    elif lower_url.endswith('xml'):
        return 'xml'
    elif lower_url.endswith('json'):
        return 'xml'
    else:
        raise ValueError('Could not infer template format from url')


def main():
    from argparse import ArgumentParser
    parser = ArgumentParser("Zabbix template syncer")
    parser.add_argument('-c', '--config', help="Configuration file path", required=True)
    args = parser.parse_args()

    config = load_config(args.config)
    zabbix_url = config['zabbix']['url']
    zabbix_token = config['zabbix']['token']
    s = requests.Session()
    s.verify = False
    with ZabbixAPI(zabbix_url, session=s) as zapi:
        zapi.login(api_token=zabbix_token)
        for template in config['templates']:
            print(f"Importing: {template}")
            t = get_upstream_template(template)
            try:
                t_type = infer_type(template)
                upload_template(zapi, t, t_type)
            except ValueError:
                print(f'Skipping due to error: {template}')


if __name__ == "__main__":
    main()
