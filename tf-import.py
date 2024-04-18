import sdwan_api, json, re, os, sys

# input parameters
target_fname = "sdwan-dbg"
target_templates = ["DC_R01_TEMPLATE"] if len (sys.argv)==1 else sys.argv[1:]
tfstate_file = "terraform.tfstate"

# working variables
target_fname_tf = f"{target_fname}.tf"
target_fname_import = f"{target_fname}-import.sh"

commented = ["id"]
skipped = [None, "template_type"]

res_type_device_template = "sdwan_feature_device_template"
res_type_device_attach = "sdwan_attach_feature_device_template"

template_type_fix = {
    "vpn_cedge_interface_cellular": "vpn_interface_cellular"
}

tf_header = \
"""
terraform {
  required_providers {
    sdwan = {
      source = "CiscoDevNet/sdwan"
      version = ">= 0.3.7"
    }
  }
}

variable "MANAGER_ADDR" { type = string }
variable "MANAGER_PASS" { type = string }
variable "MANAGER_USER" { type = string }

provider "sdwan" {
  url      = var.MANAGER_ADDR
  username = var.MANAGER_USER
  password = var.MANAGER_PASS
}

"""


variables_request = {
    'templateId': '',
    'deviceIds': [],
    'isEdited': False,
    'isMasterEdited': False,
}

# Helper function
def find_template_id (templates, name):
    """ Translate Name to ID """
    for template in templates:
        if template.get('templateName') == name:
            return template.get('templateId')
    return None

# Helper function
def find_template_name (templates, id):
    """ Translate ID to Name """
    for template in templates:
        if template.get('templateId') == id:
            return template.get('templateName')
    return None

# Helper function
class mytext:
    def __init__ (self):
        self.text = ""

    def addraw (self, line):
        self.text = self.text + line

    def add (self, line):
        self.addraw (line + "\n")

def get_var_name (field):
    """ Extract var name from long GUI name """

    result = re.search(r"\((.*)\)$", field)
    if  result:
        return result.group(1)
    else:
        return field

def process_feature_template (ftpl):

    ftpl_id = ftpl.get('templateId')
    # avoid duplicates
    if ftpl_id in seen_ftemplates:
        return 
    
    ftpl_name = find_template_name (feature_templates, ftpl_id )
    ftpl_type = ftpl["templateType"].replace("-","_")
    if ftpl_type in template_type_fix.keys():
         ftpl_type = template_type_fix[ftpl_type]
    print (f">>> TYPE: {ftpl_type}") 
    text_tf.add (f'resource "sdwan_{ftpl_type}_feature_template" "{ftpl_name}" {{\n}}')
    text_bash.add (f'terraform import sdwan_{ftpl_type}_feature_template.{ftpl_name} {ftpl_id}')
    seen_ftemplates.add(ftpl_id)

def process_device_template (template, attached, variables): 
    # text_tf, text_bash, text_att - global objects

    tID = template.get('templateId')
    tName = template.get('templateName')
    if not tID or not tName:
        print (f"Unexpected template: {template}")
        return

    text_tf.add (f'resource "sdwan_feature_device_template" "{tName}" {{\n}}')
    text_bash.add (f'terraform import sdwan_feature_device_template.{tName} {tID}')

    for ftpl in template.get('generalTemplates'):
        process_feature_template (ftpl)
        sub_ftpls = ftpl.get('subTemplates')
        if sub_ftpls:
            for sub_ftpl in sub_ftpls:
                process_feature_template (sub_ftpl)

    # this section obtains device variables for the attach, since "import" is not supported 
    # create a mapping of API "property" to GUI names
    var_index = {}
    for col in variables["header"]["columns"]:
        var_index[col["property"]] = get_var_name(col["title"])

    text_att.add (f'resource "sdwan_attach_feature_device_template" "{tName}" {{')
    text_att.add (f'  id = sdwan_feature_device_template.{tName}.id')
    text_att.add (f'  version = sdwan_feature_device_template.{tName}.version')
    text_att.add (f'  devices = [')
    for device in attached:
        text_att.add ( '    {')
        text_att.add (f'      id = "{device["uuid"]}"')
        text_att.add ( '      variables = {')
        for dev in variables["data"]:
            if dev["csv-deviceId"] == device["uuid"]:
                for key in sorted(dev.keys()):
                    if key[0] == "/":   # ignore csv-... values
                        text_att.add (f'        {var_index[key]} = "{dev[key]}"')
        text_att.add ( '      },')
        text_att.add ( '    },')
    text_att.add ( '  ]')
    text_att.add ( '}')

    return 
    
# ================== Functions for the last phase ========================
def load_tf_file (tf_file):
    try:
        with open(tf_file, "r") as content_file:
            return json.load(content_file)
    except OSError as exception:
        print (f"Unable to read device template {tf_file} ({exception})")
    except json.decoder.JSONDecodeError as exception:
        print (f"Unable to decode JSON in device template {tf_file} ({exception})")
    except:
        return None

def key_norm (key):
    return key.replace ('"', '')

def tfstate_process_list (text, res_type):
    """ process top level multiline list elements """

    out = mytext()
    lines = text.split("\n")
    for line in lines:
        if ": null" in line:
            continue
        # hacking for device templates, replace ID with TF obj reference
        # "id": "1039812038" -> "id": sdwan_cedge_aaa_feature_template.Global_AAA.id,
        if '"id":' in line and res_type == res_type_device_template:  
            l = line.split (":")
            indent = len (l[0]) - len (l[0].lstrip())
            id = all_IDs.get(l[1].split('"')[1],l[1])
            out.add (f'  {key_norm(l[0])} = {id}.id,')
            out.add (f'  {" "*indent}version = {id}.version,')
        else:  # "id": "123" -> "id" = "123"
            l = line.split (":")
            if len (l) == 2:
                out.add (f'  {key_norm(l[0])} ={l[1]}')
            else:
                out.add (f'  {line}')

    return out.text.rstrip("\n")

sort_seq = ["id", "name", "description", "device_types", "vpn_id"]

def SortFunction (item):
    try:
        idx = str(sort_seq.index (item)+1000)
    except:
        idx = "9999"
    return idx + item

# ------------------------------ start of the script ------------------------------------------
# ============ Step 0: Init
# Initialize API object
manager = os.environ.get("TF_VAR_MANAGER_ADDR") 
username = os.environ.get("TF_VAR_MANAGER_USER") 
password = os.environ.get("TF_VAR_MANAGER_PASS") 

if not manager or not username or not password:
    print ("Please define environment variables for SD-WAN access")
    exit (1)

sdwan = sdwan_api.sdwan_api (manager, username, password)

os.system(f"rm ./terraform.tfstate 2>/dev/null")
with open(target_fname_tf, "w") as file:
    file.write (tf_header)
print (f'Terraform init status: {os.system(f"terraform init")}')

# Obtain a list of all device and feature templates 
device_templates = sdwan.api_GET("/template/device")['data']
feature_templates = sdwan.api_GET("/template/feature?summary=true")['data']
text_tf = mytext()
text_bash = mytext()
text_att = mytext()
seen_ftemplates = set()


# ============ Step 1: read data from vManage, prepare empty TF structures and import script
for target_template in target_templates:
    target_template_id = find_template_id(device_templates, target_template)
    # Obtain content of device template
    template = sdwan.api_GET(f"/template/device/object/{target_template_id}")
    attached = sdwan.api_GET(f"/template/device/config/attached/{target_template_id}")['data']

    # Prepare "variables_request" data structure to request current variables
    variables_request['templateId'] = target_template_id
    for rtr in attached:
        variables_request['deviceIds'].append (rtr.get('uuid'))

    # Request device variables
    variables = sdwan.api_POST("/template/device/config/input", variables_request)

    process_device_template (template, attached, variables)

# ============ Step 2: Write skeleton TF structures and import script
with open(target_fname_tf, "w") as file:
    file.write (tf_header)
    file.write (text_tf.text)
    # file.write (text_att.text)

with open(target_fname_import, "w") as file:
    file.write ("#!/bin/bash\n\n")
    file.write (text_bash.text)

# ============ Step 3: Execute import script and populate tfstate with live data
os.system(f"chmod +x {target_fname_import}")
result = os.system(f"./{target_fname_import}")
if result != 0:
    print ("Error executing terraform import")
    exit (1)

# os.system(f"rm {target_fname_import}")

# ============ Step 4: Process tfstate into TF data
tfstate = load_tf_file (tfstate_file)
if not tfstate:
    raise SystemExit (f"Cannot load {tfstate_file} file")

text_tff = mytext()
all_IDs = {}

# First, loop through to create IDs -> Name map 
for resource in tfstate["resources"]:
    for item in resource["instances"]:
        id = item["attributes"].get("id")
        name = f'{resource["type"]}.{resource["name"]}' 
        all_IDs[id] = name  

for resource in tfstate["resources"]:
    resource_type = resource["type"]
    text_tff.add (f'resource \"{resource_type}\" \"{resource["name"]}\" {{')

    for item in resource["instances"]:

        keylist = list(item["attributes"].keys())
        keylist.sort (key = SortFunction)
        for key in keylist:
            value = item["attributes"][key]
            
            if value in skipped or key in skipped:
                continue

            # comment = "# " if key in commented else ""
            if key == "id":
                # change id to name for the "attach" resource
                if resource_type == res_type_device_attach: 
                    value = all_IDs[value] + ".id"
                else:
                    key = "# " + key

            # json formats to TF formats
            if type (value) == bool:
                value = str (value).lower()
            # if type (value) == int:
            #     value = str (value)
            if type (value) == str:
                value = '"'+value+'"'
            if type (value) == list:
                # simple list - keep 1 liner
                if type (value[0]) == str:
                    value = str(value)
                # complex structure - process line by line
                else:
                    value = tfstate_process_list (json.dumps(value, indent=2), resource_type)

                value = value.replace("'",'"')
            
            text_tff.add (f"  {key} = {value}")
    text_tff.add ("}\n")
    
# ============ Step 5: Write final TF structures + add device variables from Step 1
with open(target_fname_tf, "w") as file:
    file.write (tf_header)
    file.write (text_tff.text)
    file.write (text_att.text)

print (f'Complete, check "{target_fname_tf}" file!')

# ============ Step 6: Thank you and good bye
try:
    sdwan.logout ()
except:
    pass
