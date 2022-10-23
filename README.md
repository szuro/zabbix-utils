# zabbix-utils
Set of scripts for automating Zabbix and stuff.

# Utils list

## proxy-dashboards

A simple script that will create Zabbix Proxy performance dashboards.
Requires Zabbix > 5.4.

For detailed usage run `python3 proxy-dashboards.py -h`.

## template_syncer

A script that, when provided a config file with a list of tempale URLs,
will download a set of templates and upload them to a specified Zabbix instance via API.

For detailed usage run `python3 template_syncer.py -h`
Please, also refer to the provided sample config file.
