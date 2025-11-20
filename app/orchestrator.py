
import json

def lambda_handler(event, context):
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
