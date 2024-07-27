import sdwan_api, json, re, os, sys
from tf_library import mytext

# input parameters
target_fname = "sdwan-tf-import"
target_templates = ""
tfstate_file = "terraform.tfstate"

# working variables
target_fname_main = f"{target_fname}-config.tf"
target_fname_device = f"{target_fname}-device.tf"
target_fname_attach = f"{target_fname}-attach.tf"
target_fname_import = f"{target_fname}.sh"

commented = ["id"]
skipped = [None, "template_type"]

res_type_device_template = "sdwan_feature_device_template"
res_type_device_attach = "sdwan_attach_feature_device_template"

template_type_fix = {
    "vpn_cedge_interface_cellular": "vpn_interface_cellular"
}

sort_seq = ["id", "name", "description", "device_types", "vpn_id", 
            "shutdown", "shutdown_variable", 
            "interface_name", "interface_name_variable", 
            "interface_description", "interface_description_variable"
            "address_variable", "dhcp"]


tf_header = \
"""
terraform {
  required_providers {
    sdwan = {
      source = "CiscoDevNet/sdwan"
      version = ">= 0.3.13"
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

def get_var_name (field):
    """ Extract var name from long GUI name """

    # Use value in brackets or just return a full original name
    result = re.search(r"\((.*)\)$", field)
    value = result.group(1) if result else field

    #add quotes if space in var name. or do it always?..
    if " " in value:
        value = '"' + value + '"'

    # if  result:
    #     result = result.group(1)
    # else:
    #     result = field
    
    return value

def process_feature_template (ftpl):

    ftpl_id = ftpl.get('templateId')
    # avoid duplicates
    if ftpl_id in seen_ftemplates:
        return 
    
    ftpl_name = find_template_name (feature_templates, ftpl_id )
    ftpl_type = ftpl["templateType"].replace("-","_")
    if ftpl_type in template_type_fix.keys():
         ftpl_type = template_type_fix[ftpl_type]
    text_tf.add (f'resource "sdwan_{ftpl_type}_feature_template" "{ftpl_name}" {{\n}}')
    text_bash.add (f'terraform import sdwan_{ftpl_type}_feature_template.{ftpl_name} {ftpl_id}')
    seen_ftemplates.add(ftpl_id)

def sanitize(s):
    return re.sub("[\[\]\^\ \-\~]", "_", s)

def process_device_template (template, attached, variables): 
    # text_tf, text_bash, text_att - global objects

    tID = template.get('templateId')
    tName = sanitize(template.get('templateName'))
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

    text_attach.add (f'resource "sdwan_attach_feature_device_template" "{tName}" {{')
    text_attach.add (f'  id = sdwan_feature_device_template.{tName}.id')
    text_attach.add (f'  version = sdwan_feature_device_template.{tName}.version')
    text_attach.add (f'  devices = [')
    for device in attached:
        text_attach.add ( '    {')
        text_attach.add (f'      id = "{device["uuid"]}"')
        text_attach.add ( '      variables = {')
        for dev in variables["data"]:
            if dev["csv-deviceId"] == device["uuid"]:
                for key in sorted(dev.keys()):
                    if key[:4] != "csv-":   # ignore csv-... values
                        text_attach.add (f'        {var_index[key]} = "{dev[key]}"')
        text_attach.add ( '      },')
        text_attach.add ( '    },')
    text_attach.add ( '  ]')
    text_attach.add ( '}')

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
        # "id": "1039812038" -> "id" = sdwan_cedge_aaa_feature_template.Global_AAA.id,
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

sort_seq = ["id", "name", "description", "device_types", "vpn_id", "interface_name", "interface_description", "address_variable", "dhcp"]

def SortFunction (item):
    try:
        idx = str(sort_seq.index (item)+1000)
    except:
        idx = "9999"
    return idx + item

def text_add (text, resource_type):
    if resource_type == res_type_device_template:
        text_device.add (text)
    else:
        text_main.add (text)

def process_tfstate_file ():
    """ go through the tfstate file and extract non-default values """

    for resource in tfstate["resources"]:
        resource_type = resource["type"]
        text_add (f'resource \"{resource_type}\" \"{resource["name"]}\" {{', resource_type)

        for item in resource["instances"]:

            keylist = list(item["attributes"].keys())
            keylist.sort (key = SortFunction)
            for key in keylist:
                value = item["attributes"][key]
                
                if value in skipped or key in skipped:
                    continue

                # comment = "# " if key in commented else ""
                if key == "id":
                    key = "# " + key
                    # # change id to name for the "attach" resource
                    # if resource_type == res_type_device_attach: 
                    #     value = all_IDs[value] + ".id~~~~~~~~"
                    # else:
                    #     key = "# " + key

                # json formats to TF formats
                if type (value) == bool:
                    value = str (value).lower()
                # if type (value) == int:
                #     value = str (value)
                if type (value) == str:
                    value = value.replace("\n","\\n")   # CLI templates come with "\n" or "\r\n"
                    value = value.replace("\r","")
                    value = f'"{value}"' 
                if type (value) == list:
                    # simple list - keep 1 liner
                    if type (value[0]) == str:
                        value = str(value)
                    # complex structure - process line by line
                    else:
                        value = tfstate_process_list (json.dumps(value, indent=2), resource_type)

                    value = value.replace("'",'"')
                
                text_add (f"  {key} = {value}", resource_type)
        text_add ("}\n", resource_type)


#
# # ------------------------------ start of the script ------------------------------------------
#

# ============ Step 0: Init

if len (sys.argv)==1:
    # os.path.basename(__file__)
    print ( "Cisco SD-WAN Terraform configuration importer")
    print ( "**** DO NOT RUN IN THE PRODUCTION DIRECTORY ****\n")
    print (f"Usage: {os.path.basename(__file__)} <Device Template Name> [<Device Template Name> [<Device Template Name> ... ]]\n")
    print ( "If device template is not found, a complete list will be displayed.")
    exit (1)
target_templates = sys.argv[1:]
# target_templates = ["LAB1_SITE7_LARGE_SITE_ADJACENT1"]

# Initialize API object
manager = os.environ.get("TF_VAR_MANAGER_ADDR") 
username = os.environ.get("TF_VAR_MANAGER_USER") 
password = os.environ.get("TF_VAR_MANAGER_PASS") 

if not manager or not username or not password:
    print ("Please define TF_VAR_MANAGER_ADDR/TF_VAR_MANAGER_USER/TF_VAR_MANAGER_PASS environment variables for SD-WAN access")
    exit (1)

# Init TF: clean up old tfstate and initialize provider
os.system(f"mv ./terraform.tfstate ./terraform.tfstate.~~~bck 2>/dev/null")
with open(target_fname_main, "w") as file:
    file.write (tf_header)

tf_init_result = os.system(f"terraform init -upgrade")
if tf_init_result != 0:
    print (f'Terraform init status: {tf_init_result}')
    raise SystemExit (f"Terraform initialization failed, exiting...")

# init text structures
text_bash    = mytext(target_fname_import, "#!/bin/bash\n\n")  # bash import script
text_tf      = mytext(target_fname_main, tf_header)            # first TF skeleton
text_main    = mytext(target_fname_main, tf_header)            # final TF file: feature templates
text_device  = mytext(target_fname_device)                     # final TF file: device templates
text_attach  = mytext(target_fname_attach)                     # final TF file: "attach" resources

seen_ftemplates = set()
all_IDs = {}

# ============ Step 1: read data from vManage, prepare empty TF structures and import script
sdwan = sdwan_api.sdwan_api (manager, username, password)

# Obtain a list of all device and feature templates 
device_templates = sdwan.api_GET("/template/device")['data']
feature_templates = sdwan.api_GET("/template/feature?summary=true")['data']

for target_template in target_templates:
    target_template_id = find_template_id(device_templates, target_template)
    if not target_template_id:
        print (f"Device template {target_template} not found. The following device templates are available:")
        for template in device_templates:
            print (f"- {template.get('templateName')}")
        raise SystemExit ("Exiting...")

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
text_bash.write()
text_tf.write()

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

# Create ID -> Name map 
for resource in tfstate["resources"]:
    for item in resource["instances"]:
        id = item["attributes"].get("id")
        name = f'{resource["type"]}.{resource["name"]}' 
        all_IDs[id] = name  

process_tfstate_file ()
    
# ============ Step 5: Write final TF structures + add device variables from Step 1
text_main.write()
text_device.write()
text_attach.write()

print (f'Job complete, check *.tf file!')

# ============ Step 6: Thank you and good bye
try:
    sdwan.logout ()
except:
    pass
