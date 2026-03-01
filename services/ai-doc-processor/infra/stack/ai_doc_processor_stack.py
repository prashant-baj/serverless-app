from aws_cdk import (
    Stack,
    aws_lambda as _lambda,
    aws_s3 as s3,
    aws_s3_notifications as s3n,
    aws_apigateway as apigw,
    CfnOutput,
    aws_ecr as ecr,
    aws_iam as iam,
    RemovalPolicy,
    Duration,
    
)
from constructs import Construct

class InfraStack(Stack):

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        account = self.node.try_get_context("account") or self.account
        region = self.node.try_get_context("region") or self.region
        env_name = self.node.try_get_context("env_name") or "dev"

        print(f"Account: {account}, Region: {region}, Env Name: {env_name}")
        
         # Create ECR repo
        imagerepo = ecr.Repository(
            self,
            "AIDocProcessorImageRepo",
            repository_name=f"ai-doc-processor-repo-{env_name}"
        )
        
        
        # Create an S3 bucket that will trigger the Lambda
        bucket = s3.Bucket(self, "AIDocProcessingBucket",
                           removal_policy=RemovalPolicy.DESTROY, # NOT for production
                           auto_delete_objects=True) # NOT for production

        # Create the Lambda function
        # orchestrator_lambda = _lambda.Function(
        #     self, "OrchestratorLambda",
        #     runtime=_lambda.Runtime.PYTHON_3_9,
        #     handler="orchestrator.lambda_handler",
        #     code=_lambda.Code.from_asset("../app")
        # )
        # Lambda Function
        
        orchestrator_lambda_name = f"OrchestratorContainer-{env_name}"
       
        orchestrator_lambda = _lambda.DockerImageFunction(
            self,
            "DocumentProcessingOrchestrator",
            function_name=orchestrator_lambda_name,
            code=_lambda.DockerImageCode.from_image_asset(
                "../app/orchestrator",  # folder containing Dockerfile
                build_args={                    
                    "MODEL_ID": f"arn:aws:bedrock:{region}:{account}:inference-profile/apac.anthropic.claude-sonnet-4-20250514-v1:0",
                    "PROMPT_BUCKET": "prompts-dev",
                    "PROMPT_KEY": "orchestrator/Orchestrator.txt"                   
                },
            ),
            timeout=Duration.minutes(10),
            reserved_concurrent_executions=1,  # To limit to 1 concurrent execution
            
        )

        # Add S3 trigger to the Lambda function
        bucket.add_event_notification(
            s3.EventType.OBJECT_CREATED,
            s3n.LambdaDestination(orchestrator_lambda)
        )
        
        # Grant the Lambda function read permissions on the bucket
        bucket.grant_read(orchestrator_lambda)

        # Add IAM policies for Textract and Bedrock
        textract_policy = iam.PolicyStatement(
            actions=["textract:*"],
            resources=["*"]
        )
        bedrock_policy = iam.PolicyStatement(
            actions=[
                "bedrock:InvokeModel",                
                "bedrock:InvokeModelWithResponseStream",
                "bedrock:ListFoundationModels",
                "bedrock:ListPrompts",
                "bedrock:GetPrompt",
                "bedrock:ListPromptVersions",
                "bedrock-agentcore:InvokeAgentRuntime"
            ],
            resources=["*"]
        )

        orchestrator_lambda.add_to_role_policy(textract_policy)
        orchestrator_lambda.add_to_role_policy(bedrock_policy)

        # Create an API Gateway to invoke the Lambda
        api = apigw.LambdaRestApi(
            self, "AIDocProcessorApi",
            handler=orchestrator_lambda,
            proxy=False
        )
        
        items = api.root.add_resource("items")
        items.add_method("GET")
        

        CfnOutput(self, "ApiUrl", value=api.url)
