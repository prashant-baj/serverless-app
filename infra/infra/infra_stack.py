from aws_cdk import (
    Stack,
    aws_lambda as _lambda,
    aws_s3 as s3,
    aws_s3_notifications as s3n,
    aws_apigateway as apigw,
    RemovalPolicy,
    CfnOutput
)
from constructs import Construct

class InfraStack(Stack):

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # Create an S3 bucket that will trigger the Lambda
        bucket = s3.Bucket(self, "DocumentBucket",
                           removal_policy=RemovalPolicy.DESTROY, # NOT for production
                           auto_delete_objects=True) # NOT for production

        # Create the Lambda function
        orchestrator_lambda = _lambda.Function(
            self, "OrchestratorLambda",
            runtime=_lambda.Runtime.PYTHON_3_9,
            handler="orchestrator.lambda_handler",
            code=_lambda.Code.from_asset("../app")
        )

        # Add S3 trigger to the Lambda function
        bucket.add_event_notification(
            s3.EventType.OBJECT_CREATED,
            s3n.LambdaDestination(orchestrator_lambda)
        )
        
        # Grant the Lambda function read permissions on the bucket
        bucket.grant_read(orchestrator_lambda)

        # Create an API Gateway to invoke the Lambda
        api = apigw.LambdaRestApi(
            self, "Endpoint",
            handler=orchestrator_lambda,
            proxy=False
        )
        
        items = api.root.add_resource("items")
        items.add_method("GET")
        

        CfnOutput(self, "ApiUrl", value=api.url)
