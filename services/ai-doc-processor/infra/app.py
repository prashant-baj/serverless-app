#!/usr/bin/env python3
import os

import aws_cdk as cdk

from infra.infra_stack import InfraStack


app = cdk.App()

# Get account and region from CDK context
account = app.node.try_get_context("account") or os.getenv('CDK_DEFAULT_ACCOUNT')
region = app.node.try_get_context("region") or os.getenv('CDK_DEFAULT_REGION')
env_name = app.node.try_get_context("env_name") or "dev"

if not account or not region:
    raise ValueError("Please provide AWS account and region via CDK context (-c account=... -c region=...) or set CDK_DEFAULT_ACCOUNT and CDK_DEFAULT_REGION environment variables.")

env = cdk.Environment(account=account, region=region)

InfraStack(app, "AIDocProcessorStack", env=env)

app.synth()
