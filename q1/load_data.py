import boto3
import json
import argparse
import re
import sys
from collections import Counter
from stopwords import STOPWORDS
from boto3.dynamodb.types import TypeSerializer

def get_or_create_table(dynamodb, table_name):
    try:
        table = dynamodb.create_table(
            TableName=table_name,
            KeySchema=[
                {'AttributeName': 'PK', 'KeyType': 'HASH'},
                {'AttributeName': 'SK', 'KeyType': 'RANGE'}
            ],
            AttributeDefinitions=[
                {'AttributeName': 'PK', 'AttributeType': 'S'},
                {'AttributeName': 'SK', 'AttributeType': 'S'},
                {'AttributeName': 'AuthorPK', 'AttributeType': 'S'},
                {'AttributeName': 'AuthorSK', 'AttributeType': 'S'},
                {'AttributeName': 'KeywordPK', 'AttributeType': 'S'},
                {'AttributeName': 'KeywordSK', 'AttributeType': 'S'},
                {'AttributeName': 'PaperPK', 'AttributeType': 'S'},
                {'AttributeName': 'PaperSK', 'AttributeType': 'S'}
            ],
            BillingMode='PAY_PER_REQUEST',
            GlobalSecondaryIndexes=[
                {
                    'IndexName': 'AuthorIndex',
                    'KeySchema': [
                        {'AttributeName': 'AuthorPK', 'KeyType': 'HASH'},
                        {'AttributeName': 'AuthorSK', 'KeyType': 'RANGE'}
                    ],
                    'Projection': {'ProjectionType': 'ALL'}
                },
                {
                    'IndexName': 'KeywordIndex',
                    'KeySchema': [
                        {'AttributeName': 'KeywordPK', 'KeyType': 'HASH'},
                        {'AttributeName': 'KeywordSK', 'KeyType': 'RANGE'}
                    ],
                    'Projection': {'ProjectionType': 'ALL'}
                },
                {
                    'IndexName': 'PaperIdIndex',
                    'KeySchema': [
                        {'AttributeName': 'PaperPK', 'KeyType': 'HASH'},
                        {'AttributeName': 'PaperSK', 'KeyType': 'RANGE'}
                    ],
                    'Projection': {'ProjectionType': 'ALL'}
                }
            ]
        )
        print(f"Creating DynamoDB table: {table_name}")
        print("Creating GSIs: AuthorIndex, PaperIdIndex, KeywordIndex")
        table.meta.client.get_waiter('table_exists').wait(TableName=table_name)
        return table
    except dynamodb.meta.client.exceptions.ResourceInUseException:
        print(f"Table {table_name} already exists. Reusing it.")
        table = dynamodb.Table(table_name)
        table.meta.client.get_waiter('table_exists').wait(TableName=table_name)
        return table

def extract_keywords(abstract):
    words = re.findall(r'[a-z0-9]+', abstract.lower())
    valid_words = [w for w in words if w not in STOPWORDS]
    counts = Counter(valid_words)
    return [word for word, _ in counts.most_common(10)]

def batch_write_with_retries(client, table_name, items):
    serializer = TypeSerializer()
    requests = []
    
    for item in items:
        serialized = {k: serializer.serialize(v) for k, v in item.items()}
        requests.append({"PutRequest": {"Item": serialized}})

    for i in range(0, len(requests), 25):
        batch = requests[i:i+25]
        request_params = {table_name: batch}
        
        while request_params:
            response = client.batch_write_item(RequestItems=request_params)
            unprocessed = response.get('UnprocessedItems', {})
            
            if unprocessed and table_name in unprocessed and unprocessed[table_name]:
                request_params = unprocessed
            else:
                request_params = None

def main():
    parser = argparse.ArgumentParser(description="Load arXiv papers into DynamoDB")
    parser.add_argument('papers_json_path')
    parser.add_argument('table_name')
    parser.add_argument('--region', default='us-west-2')
    args = parser.parse_args()

    dynamodb_res = boto3.resource('dynamodb', region_name=args.region)
    dynamodb_client = boto3.client('dynamodb', region_name=args.region)
    
    get_or_create_table(dynamodb_res, args.table_name)

    print(f"Loading papers from {args.papers_json_path}...")
    with open(args.papers_json_path, 'r') as f:
        papers = json.load(f)

    print("Extracting keywords from abstracts...")
    all_items = []
    
    stats = {
        "papers": len(papers),
        "categories": 0,
        "authors": 0,
        "keywords": 0,
        "paper_ids": 0
    }

    for paper in papers:
        arxiv_id = paper.get('id', paper.get('arxiv_id'))
        base_item = {
            "arxiv_id": arxiv_id,
            "title": paper["title"],
            "authors": paper["authors"],
            "abstract": paper["abstract"],
            "categories": paper["categories"],
            "published": paper["published"],
            "keywords": extract_keywords(paper["abstract"])
        }
        
        sk_val = f"{base_item['published']}#{arxiv_id}"

        for cat in base_item["categories"]:
            item = base_item.copy()
            item["PK"] = f"CATEGORY#{cat}"
            item["SK"] = sk_val
            all_items.append(item)
            stats["categories"] += 1

        for author in base_item["authors"]:
            item = base_item.copy()
            item["PK"] = f"ITEM#{arxiv_id}#AUTHOR#{author}"
            item["SK"] = sk_val
            item["AuthorPK"] = f"AUTHOR#{author}"
            item["AuthorSK"] = sk_val
            all_items.append(item)
            stats["authors"] += 1

        for kw in base_item["keywords"]:
            item = base_item.copy()
            item["PK"] = f"ITEM#{arxiv_id}#KEYWORD#{kw}"
            item["SK"] = sk_val
            item["KeywordPK"] = f"KEYWORD#{kw}"
            item["KeywordSK"] = sk_val
            all_items.append(item)
            stats["keywords"] += 1

        item = base_item.copy()
        item["PK"] = f"ITEM#{arxiv_id}"
        item["SK"] = sk_val
        item["PaperPK"] = f"PAPER#{arxiv_id}"
        item["PaperSK"] = sk_val
        all_items.append(item)
        stats["paper_ids"] += 1

    batch_write_with_retries(dynamodb_client, args.table_name, all_items)
    
    total_items = len(all_items)
    avg = lambda x: x / stats["papers"]

    print(f"Loaded {stats['papers']} papers")
    print(f"Created {total_items} DynamoDB items (denormalized)")
    print(f"Denormalization factor: {total_items/stats['papers']:.1f}x\n")
    print("Storage breakdown:")
    print(f"- Category items: {stats['categories']} ({avg(stats['categories']):.1f} per paper avg)")
    print(f"- Author items: {stats['authors']} ({avg(stats['authors']):.1f} per paper avg)")
    print(f"- Keyword items: {stats['keywords']} ({avg(stats['keywords']):.1f} per paper avg)")
    print(f"- Paper ID items: {stats['paper_ids']} ({avg(stats['paper_ids']):.1f} per paper)")

if __name__ == '__main__':
    main()
