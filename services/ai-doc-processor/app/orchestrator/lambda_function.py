
import json
import os
import time
import uuid
import hashlib
from typing import Any, Dict, Optional

import boto3
from strands import Agent, tool
from strands.models import BedrockModel
from datetime import datetime
from zoneinfo import ZoneInfo

MODEL_ID = os.getenv("MODEL_ID")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
PROMPT_BUCKET = os.getenv("PROMPT_BUCKET")
PROMPT_KEY = os.getenv("PROMPT_KEY")
AWS_REGION = os.getenv("AWS_REGION")
AWS_DEFAULT_REGION = os.getenv("AWS_DEFAULT_REGION", AWS_REGION)

ENV_NAME = os.getenv("ENV_NAME", "dev")
lambda_client = boto3.client("lambda", region_name=AWS_REGION)

EXTRACTION_AGENT_LAMBDA = os.getenv("EXTRACTION_AGENT_LAMBDA", f"InvoiceExtractionContainer-{ENV_NAME}")


@tool(name="send_whatsapp_notification", description="Send WhatsApp notification with extracted invoice data")
def send_whatsapp_notification(
    extracted_data: str = None,
    processId: Optional[str] = None,
) -> str:
    # Simulate sending WhatsApp notification (to be replaced with actual implementation)
    print("Sending WhatsApp notification with the following data:", extracted_data)
    return json.dumps("Send WhatsApp Notification Tool Invoked Successfully")

@tool(name="perform_invoice_posting_to_sap", description="Post extracted invoice data to SAP system")
def perform_invoice_posting_to_sap(
    extracted_data: str = None,
    processId: Optional[str] = None,
) -> str:
    # Simulate posting to SAP (to be replaced with actual implementation)
    print("Posting the following data to SAP system:", extracted_data)
    return json.dumps("Perform Invoice Posting to SAP Tool Invoked Successfully")


@tool(name="validate_invoice_data", description="Validate extracted invoice data")
def validate_invoice_data(
    extracted_data: Optional[Dict[str, Any]] = None,
    processId: Optional[str] = None,
) -> str:
    # Simple validation logic (to be expanded as needed)
    required_fields = ["invoice_number", "date", "total_amount", "vendor_name"]
    # missing_fields = [field for field in required_fields if field not in extracted_data]

    # if missing_fields:
    #     validation_result = {
    #         "processId": processId,
    #         "is_valid": False,
    #         "missing_fields": missing_fields,
    #         "message": f"Missing required fields: {', '.join(missing_fields)}"
    #     }
    # else:
    #     validation_result = {
    #         "processId": processId,
    #         "is_valid": True,
    #         "message": "All required fields are present."
    #     }

    print("Validation is performed on the extracted data:", required_fields)
    return json.dumps("Validate Invoice Data Tool Invoked Successfully")


@tool(name="textract_extraction_agent", description="Extract text/data from document using Textract agent Lambda")
def textract_extraction_agent(
    bucket: Optional[str] = None,
    key: Optional[str] = None,
    processId: Optional[str] = None,
) -> str:
    
    payload = {
        "processId": processId,
        "tool": "extract_document",
        "parameters": {"s3_bucket": bucket, "s3_key": key, "imageOutputPath": "imageOutput"},
    }

    print("Invoking extraction Lambda:", EXTRACTION_AGENT_LAMBDA, "with payload keys:", list(payload.keys()))   
    # resp = lambda_client.invoke(
    #     FunctionName=EXTRACTION_AGENT_LAMBDA,
    #     InvocationType="RequestResponse",
    #     Payload=json.dumps(payload),
    # )
    # raw = resp["Payload"].read().decode("utf-8")
    # parsed = json.loads(raw)
    # extract = parsed.get("extracted_table") or parsed.get("output") or parsed
    # kv = parsed.get("kv") or {}

    # result = {
    #     "processId": processId,
    #     "inputFile": f"{bucket}/{key}",        
    #     "extracted_data": parsed,
    #     "meta-info": "extracted_data is the information in the document"
   
    # }
    
    
    return json.dumps("Extraction Lambda Tool Invoked Successfully")






def lambda_handler(event, context):
    print("Starting Lambda handler execution.")
    """
    This Lambda function acts as an orchestrator for a document processing pipeline.
    It can be triggered by an S3 object put event or invoked via HTTP.
    """
    print(f"Received event: {json.dumps(event)}")

    # Check if the invocation is from S3
    if 'Records' in event and event['Records'][0].get('eventSource') == 'aws:s3':
        print("Invocation from S3 detected.")
        
        # TODO: Add document processing pipeline orchestration logic here.
        # For example, start a Step Function, invoke another Lambda, etc.
        
        s3_info = event['Records'][0]['s3']
        bucket_name = s3_info['bucket']['name']
        object_key = s3_info['object']['key']
        
        print(f"Processing file '{object_key}' from bucket '{bucket_name}'.")
        print("Starting document processing pipeline with {MODEL_ID}, {AWS_REGION}...")
         # Orchestrator Agent
        bedrock_model = BedrockModel(model_id=MODEL_ID, region_name=AWS_REGION, streaming=False)
        orchestrator = Agent(
            model=bedrock_model,
            name="DocumentExtractionOrchestrator",
            description="Runs tool-driven pipeline for document extraction and processing.",
            system_prompt="You're an orchestrator agent that coordinates various document processing tasks using specialized tools." \
            " You decide which tool to use based on the input document and the desired output." \
            " Output of can be considered as input to the next tool in the pipeline." \
            " Send whatsapp notification when the processing starts and ends.",
            tools=[
                textract_extraction_agent,
                validate_invoice_data,
                perform_invoice_posting_to_sap,
                send_whatsapp_notification,                
            ],        
        )
        result = orchestrator("Run the invoice processing pipeline. Key inputs are s3 bucket and key. S3 Bucket name is {} and object key is {}.".format(bucket_name, object_key),)       
        print("Orchestration result:", result)
         
        return {
            'statusCode': 200,
            'body': json.dumps({
                'message': 'S3 event processed successfully.',
                'bucket': bucket_name,
                'key': object_key
            })
        }
    
    # Check if the invocation is from API Gateway (HTTP)
    elif 'httpMethod' in event:
        print("Invocation from HTTP detected.")
        return {
            'statusCode': 200,
            'headers': {
                'Content-Type': 'text/plain'
            },
            'body': 'Thank you for connecting me. However, I am expected to process a document when a document is upload to S3 bucket.'
        }
        
    # Default response for other invocation types
    else:
        print("Invocation from an unknown source detected.")
        return {
            'statusCode': 400,
            'body': json.dumps('Unknown invocation source.')
        }
