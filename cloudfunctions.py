from json import dumps, loads
import sys
from httplib2 import Http
import base64
import time

def main(event, context):
    """Triggered from a message on a Cloud Pub/Sub topic.
    Args:
         event (dict): Event payload.
         context (google.cloud.functions.Context): Metadata for the event.
    """
    pubsub_message = base64.b64decode(event['data']).decode('utf-8')
    pubsub_msg_dict = loads(pubsub_message)
    source = pubsub_msg_dict["source"]
    attr_dict = event['attributes']
    buildId = attr_dict["buildId"]

    dpt_git_url = "https://github.com/GoogleCloudPlatform/dataproc-templates.git"
    if "gitSource" not in pubsub_msg_dict["source"]:
        print("Invalid CloudBuild Trigger found, Exiting...")
        exit(0)
    elif source["gitSource"]["url"] == dpt_git_url:
        print("DPT Git Trigger Found")

    # Google Chat incoming webhook
    gchat_space_url = ''
    status = pubsub_msg_dict["status"]
    logUrl = pubsub_msg_dict["logUrl"]
    release_tag = pubsub_msg_dict["substitutions"]["TAG_NAME"]
    pypi_dpt_latest = "https://pypi.org/project/google-dataproc-templates/"
    binaries_deployment_bucket_latest = "gs://dataproc-templates-binaries/latest/"
    git_release_latest = "https://github.com/GoogleCloudPlatform/dataproc-templates/releases/latest"

    TRIGGER_NAME = pubsub_msg_dict["substitutions"]["TRIGGER_NAME"]
    if TRIGGER_NAME not in ["promote-java-binaries", "build-binaries"]:
        print(f"The cloud build {TRIGGER_NAME} is not supported. Exiting now...")
        sys.exit(0)

    if status in ["SUCCESS", "FAILURE", "TIMEOUT", "EXPIRED", "INTERNAL_ERROR", "STATUS_UNKNOWN"]:
        print("Generating chat message")

        if TRIGGER_NAME == "build-binaries":
            bot_message = {
            'text': "DPT New Release Deployment Job: Build Binaries 🛠️" +
            "\nDeployment Status: " + status + 
            "\nRelease Tag: " + release_tag + 
            "\nGit Release: " + git_release_latest +
            "\nCloud Build Log URL: " + logUrl + 
            "\n\nIf the status is successful, the release artifact build and integration tests have successfully completed and artifact promotion is pending. You will shortly recieve a seperate request to approve/reject the artifact promotion."
            }   
        elif TRIGGER_NAME == "promote-java-binaries":
            bot_message = {
            'text': "DPT New Release Deployment Job: Promote Binaries 🚀" +
            "\nDeployment Status: " + status + 
            "\nRelease Tag: " + release_tag + 
            "\nBinaries Public Bucket: " + binaries_deployment_bucket_latest + 
            "\nPypi Release: " + pypi_dpt_latest + 
            "\nGit Release: " + git_release_latest +
            "\nCloud Build Log URL: " + logUrl + 
            "\n\nNote: If the status is successful, the release deployment process is now complete, and the built binaries have been promoted to the public DPT binary bucket."
            }

        message_headers = {'Content-Type': 'application/json; charset=UTF-8'}
        http_obj = Http()
        response = http_obj.request(
            uri=gchat_space_url,
            method='POST',
            headers=message_headers,
            body=dumps(bot_message),
        )
        print(response)
    elif status == "PENDING":
        if "approval" in pubsub_msg_dict and pubsub_msg_dict["approval"]["config"]["approvalRequired"]:
            time.sleep(20)
            print("Generating chat message for PENDING approval...")
            bot_message = {
                'text': "DPT New Release Deployment Job: Artifact promotion requires your approval! ⏳" + 
                "\nDeployment Status: " + status + 
                "\nRelease Tag: " + release_tag + 
                "\nGit Release: " + git_release_latest + 
                "\n\nYou are receiving this message because the artifact build and integration tests have successfully completed for this release. Upon your approval, the built artifact will be deployed to the public DPT binary bucket.\n\nPlease provide your approval at: "+ logUrl 
            }

            message_headers = {'Content-Type': 'application/json; charset=UTF-8'}
            http_obj = Http()
            response = http_obj.request(
                uri=gchat_space_url,
                method='POST',
                headers=message_headers,
                body=dumps(bot_message),
            )
            print(response)
    elif status == "CANCELLED":
        if "approval" in pubsub_msg_dict and pubsub_msg_dict["approval"]["config"]["approvalRequired"]:
            print("Generating chat message for REJECTED/CANCELLED approval...")
            bot_message = {
                'text': "A DPT release artifact deployment has been " + pubsub_msg_dict["approval"]["state"] +"! ❌" + 
                "\nRelease Tag: " + release_tag + 
                "\nGit Release: " + git_release_latest + 
                "\n\nReview more details at Cloud Build URL: "+ logUrl 
            }

            message_headers = {'Content-Type': 'application/json; charset=UTF-8'}
            http_obj = Http()
            response = http_obj.request(
                uri=gchat_space_url,
                method='POST',
                headers=message_headers,
                body=dumps(bot_message),
            )
            print(response)
    print("Cloud Build Status message submitted to chat space")
