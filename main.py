import json
import os
import random
import shlex
import urllib
import urllib2
import re

import logging

logging.basicConfig(format='%(message)s', level=logging.INFO)
log = logging.getLogger(__name__)
log.setLevel(logging.DEBUG)
logging.getLogger("requests.packages.urllib3").setLevel(logging.ERROR)

# Mapping CloudFormation status codes to colors for Slack message attachments
# Status codes from http://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/using-cfn-describing-stacks.html
STATUS_COLORS = {
    'CREATE_COMPLETE': 'good',
    'CREATE_IN_PROGRESS': 'warning',
    'CREATE_FAILED': 'danger',
    'DELETE_COMPLETE': 'good',
    'DELETE_FAILED': 'danger',
    'DELETE_IN_PROGRESS': 'warning',
    'ROLLBACK_COMPLETE': 'danger',
    'ROLLBACK_FAILED': 'danger',
    'ROLLBACK_IN_PROGRESS': 'warning',
    'UPDATE_COMPLETE': 'good',
    'UPDATE_COMPLETE_CLEANUP_IN_PROGRESS': 'warning',
    'UPDATE_IN_PROGRESS': 'warning',
    'UPDATE_ROLLBACK_COMPLETE': 'good',
    'UPDATE_ROLLBACK_COMPLETE_CLEANUP_IN_PROGRESS': 'danger',
    'UPDATE_ROLLBACK_FAILED': 'danger',
    'UPDATE_ROLLBACK_IN_PROGRESS': 'danger'
}

# List of CloudFormation status that will trigger a call to `get_stack_summary_attachment`
DESCRIBE_STACK_STATUS = [
    'CREATE_COMPLETE',
    'UPDATE_COMPLETE',
    'DELETE_COMPLETE'
]

# List of properties from ths SNS message that will be included in a Slack message
SNS_PROPERTIES_FOR_SLACK = [
    'Namespace',
    'StackName',
]


def lambda_handler(event, context):
    log.info("Event: {}".format(json.dumps(event, indent=4)))
    message = event['Records'][0]['Sns']
    sns_message = message['Message']
    cf_message = dict(token.split('=', 1) for token in shlex.split(sns_message))
    log.info("CloudFormation Message:: {}".format(json.dumps(cf_message, indent=4)))

    # ignore messages that do not pertain to the Stack as a whole
    is_stack = cf_message['ResourceType'] == 'AWS::CloudFormation::Stack'
    is_self = cf_message['LogicalResourceId'] == cf_message['StackName']
    if not (is_stack and is_self):
        log.info("Message ignored.")
        return

    message = create_message(cf_message, message['TopicArn'], message['Subject'])
    data = json.dumps(message, indent=4)
    webhook_url = os.getenv('WEBHOOK')

    log.info("Webhook url is %s", webhook_url)
    req = urllib2.Request(webhook_url, data, {'Content-Type': 'application/json'})
    res = urllib2.urlopen(req)
    log.info("Message sent, %s received.", res.getcode())


def create_message(cf_message, sns_arn, sns_subject):
    attachments = [
        create_attachment(cf_message, sns_arn)
    ]

    randoms = [':hypnotoad:', ':corbinspin:']
    for _ in range(1, 8):
        randoms.append(':cloudformation:')

    emoji = random.choice(randoms)
    message = {
        'icon_emoji': emoji,
        'attachments': attachments
    }

    if os.getenv('CHANNEL'):
        message['channel'] = os.getenv('CHANNEL')

    return message


def create_attachment(cf_message, sns_arn):
    stack_url = get_stack_url(cf_message['StackId'])
    stack_name = cf_message['StackName']

    if cf_message['ResourceStatusReason'] in ('', None):
        text = "{}".format(cf_message['ResourceStatus'], cf_message['ResourceStatusReason'])
    else:
        text = "{}: {}".format(cf_message['ResourceStatus'], cf_message['ResourceStatusReason'])

    fields = []
    for k in SNS_PROPERTIES_FOR_SLACK:
        v = cf_message[k]
        same_stack_and_logical_name = \
            k == 'LogicalResourceId' and cf_message['StackName'] == cf_message['LogicalResourceId']

        if same_stack_and_logical_name:
            v = None

        fields.append({
            'title': 'Account ID' if k == 'Namespace' else k,
            'value': v,
            'short': True
        })

    fields.append({
        'title': 'Stack Events',
        'value': '<{url}|View {name} in the AWS console>'.format(url=stack_url, name=stack_name),
        'short': False
    })

    return {
        'mrkdwn_in': ['text', 'pretext'],
        'fallback': text,
        'author_name': 'AWS CloudFormation',
        'author_icon': 'https://github.com/danieljimenez/cf-notify/raw/master/aws_cloudformation.png',
        'author_link': 'https://console.aws.amazon.com/cloudformation/home',
        'text': text,
        'footer': sns_arn,
        'footer_icon': 'https://github.com/danieljimenez/cf-notify/raw/master/aws_sns.png',
        'footer_link': 'https://console.aws.amazon.com/sns/v2/home#/topics/{arn}'.format(arn=sns_arn),
        'fields': fields,
        'color': STATUS_COLORS.get(cf_message['ResourceStatus'], '#000000'),
    }


def get_stack_region(stack_id):
    regex = re.compile('arn:aws:cloudformation:(?P<region>[a-z]{2}-[a-z]{4,9}-[1-2]{1})')
    return regex.match(stack_id).group('region')


def get_stack_url(stack_id):
    region = get_stack_region(stack_id)

    return ('https://{region}.console.aws.amazon.com/cloudformation/home?region={region}#/stack/detail?stackId={stackId}'.format(
        region=region,
        stackId=stack_id.replace('/', '%2F')
    ))
