import re
import os
import yaml


def subs_str(s):
    res = re.sub(r':', ': ', s)
    return re.sub(':\s+', ': ', res)


def get_role_name(file_name):
    name = file_name.split('/')
    name = os.path.splitext(name[1])[0]
    return name


def parse_key(key):
    res = key.split('::')
    res.pop(-1)
    if len(res) > 1:
        res = '::'.join()

        return res
    return res[0]


def parse_prop(key):
    res = key.split('::')
    return res.pop(-1)


def from_yaml_to_dict(file_name, REPOSITORY_PATH):
    with open(REPOSITORY_PATH + '/' + file_name) as f:
        data = yaml.safe_load(f)
    return data


def change_role_content(from_role, to_role, REPOSITORY_PATH):
        file_from = 'roles/' + from_role + '.yaml'
        with open(REPOSITORY_PATH + '/' + file_from) as f:
                data_map = yaml.safe_load(f)

        file_to = 'roles/' + to_role + '.yaml'
        with open(REPOSITORY_PATH + '/' + file_to, 'w+') as f:
                yaml.safe_dump(data_map, f,  explicit_start=True, default_flow_style=False)
        return data_map
