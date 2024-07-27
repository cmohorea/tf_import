#Cisco SD-WAN Terraform configuration importer
##Requirements
- python
- python libraries: requests
- terraform
- API access to SD-WAN Manager (vManage)

## What does it do?
This script imports 3 types of terraform resources from the existing SD-WAN deployments
1. Device templates, as specified in command line
2. All the feature templates used by these device templates.
3. Device attach resources that include provisioning values for the device templates.

## How to run
1. Clone the repository
2. Enter the repository directory
3. Define TF_VAR_MANAGER_ADDR/TF_VAR_MANAGER_USER/TF_VAR_MANAGER_PASS environment variables for SD-WAN Manager (vManage) API access
4. Execute `tf_import.py` script. Supply name(s) of SD-WAN device templates to process,

## Notes
- Provide non-existing template name and script will print all the known device template names
- Run script just one time, specifying all the device templates you're interested in rather than running script for each device template. This would avoid duplication of feature template resources that are used in multiple device templates.
- Script creates and removed working data, including the `tfstate.tf` file. Do not run the script in the production directory to avoid losing it.
- Diagnostics and error handling is minimal, script just exits when something unexpected happends.
