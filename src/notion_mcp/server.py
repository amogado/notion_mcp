from mcp.server import Server
from mcp.types import (
    Resource, 
    Tool,
    TextContent,
    EmbeddedResource
)
from pydantic import AnyUrl
import os
import json
from datetime import datetime
import httpx
from typing import Any, Sequence
from dotenv import load_dotenv
from pathlib import Path
import logging

# Set up logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger('notion_mcp')

# Find and load .env file from project root
project_root = Path(__file__).parent.parent.parent
env_path = project_root / '.env'
if not env_path.exists():
    raise FileNotFoundError(f"No .env file found at {env_path}")
load_dotenv(env_path)

# Initialize server
server = Server("notion-todo")

# Configuration with validation
NOTION_API_KEY = os.getenv("NOTION_API_KEY")
DATABASE_ID = os.getenv("NOTION_DATABASE_ID")

if not NOTION_API_KEY:
    raise ValueError("NOTION_API_KEY not found in .env file")
if not DATABASE_ID:
    raise ValueError("NOTION_DATABASE_ID not found in .env file")

NOTION_VERSION = "2022-06-28"
NOTION_BASE_URL = "https://api.notion.com/v1"

# Notion API headers
headers = {
    "Authorization": f"Bearer {NOTION_API_KEY}",
    "Content-Type": "application/json",
    "Notion-Version": NOTION_VERSION
}

async def fetch_todos() -> dict:
    """Fetch todos from Notion database"""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{NOTION_BASE_URL}/databases/{DATABASE_ID}/query",
            headers=headers,
            json={
                "sorts": [
                    {
                        "timestamp": "created_time",
                        "direction": "descending"
                    }
                ],
                "page_size": 50  # Limit results to 50 elements
            }
        )
        response.raise_for_status()
        return response.json()

@server.list_tools()
async def list_tools() -> list[Tool]:
    """List available todo tools"""
    return [
        Tool(
            name="show_all_notion_pages",
            description="Show all Notion pages from the database given in the configuration",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": []
            }
        ),
        Tool(
            name="notion_update_status",
            description="Update the Status of a Notion page",
            inputSchema={
                "type": "object",
                "properties": {
                    "page_id": {
                        "type": "string",
                        "description": "The ID of the Notion page to update"
                    },
                    "target_status": {
                        "type": "string",
                        "description": "The status to set (e.g., 'Done', 'In Progress', 'To Do', etc.)"
                    }
                },
                "required": ["page_id", "target_status"]
            }
        ),
        Tool(
            name="notion_read_page_content",
            description="Read the content of a Notion page",
            inputSchema={
                "type": "object",
                "properties": {
                    "page_id": {
                        "type": "string",
                        "description": "The ID of the Notion page to read"
                    }
                },
                "required": ["page_id"]
            }
        ),
        Tool(
            name="notion_update_page_content",
            description="Update the content of a Notion page",
            inputSchema={
                "type": "object",
                "properties": {
                    "page_id": {
                        "type": "string",
                        "description": "The ID of the Notion page to update"
                    },
                    "content": {
                        "type": "array",
                        "description": "Array of content blocks to add to the page",
                        "items": {
                            "type": "object",
                            "properties": {
                                "type": {
                                    "type": "string",
                                    "description": "The type of block (paragraph, heading_1, etc.)"
                                },
                                "text": {
                                    "type": "string",
                                    "description": "The text content of the block"
                                }
                            },
                            "required": ["type", "text"]
                        }
                    }
                },
                "required": ["page_id", "content"]
            }
        ),
        Tool(
            name="notion_add_comment",
            description="Add a comment to a Notion page",
            inputSchema={
                "type": "object",
                "properties": {
                    "page_id": {
                        "type": "string",
                        "description": "The ID of the Notion page to add a comment to"
                    },
                    "comment": {
                        "type": "string",
                        "description": "The comment text to add"
                    },
                    "icon": {
                        "type": "string",
                        "description": "The emoji to use as the comment icon (optional)",
                        "default": "💬"
                    }
                },
                "required": ["page_id", "comment"]
            }
        )
    ]

async def get_page_content(page_id: str) -> dict:
    """Fetch page content from Notion"""
    async with httpx.AsyncClient() as client:
        # First get the page properties
        response = await client.get(
            f"{NOTION_BASE_URL}/pages/{page_id}",
            headers=headers
        )
        response.raise_for_status()
        page_data = response.json()

        # Then get the page blocks (content)
        blocks_response = await client.get(
            f"{NOTION_BASE_URL}/blocks/{page_id}/children",
            headers=headers
        )
        blocks_response.raise_for_status()
        blocks_data = blocks_response.json()

        return {
            "properties": page_data.get("properties", {}),
            "content": blocks_data.get("results", [])
        }

@server.call_tool()
async def call_tool(name: str, arguments: Any) -> Sequence[TextContent | EmbeddedResource]:
    """Handle tool calls for todo management"""
    if name == "show_all_notion_pages":
        try:
            # Fetch all pages from the database
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{NOTION_BASE_URL}/databases/{DATABASE_ID}/query",
                    headers=headers,
                    json={
                        "page_size": 500,  # Maximum number of pages to retrieve
                        "sorts": [
                            {
                                "property": "Created time",
                                "timestamp": "created_time",
                                "direction": "descending"
                            }
                        ]
                    }
                )
                response.raise_for_status()
                pages = response.json()

                # Extract and format the pages information
                formatted_pages = []
                for page in pages.get("results", []):
                    title = extract_text_from_title(page.get("properties", {}).get("Title", {}))
                    formatted_pages.append({
                        "id": page.get("id", ""),
                        "title": title,
                        "clients": extract_multi_select(page.get("properties", {}).get("Clients", {})),
                        "Created time": page.get("created_time", ""),
                        "Last edited time": page.get("last_edited_time", ""),
                        "url": f"https://www.notion.so/{page.get('id', '').replace('-', '')}",
                        "status": extract_select(page.get("properties", {}).get("Status", {})),
                    })

                return [
                    TextContent(
                        type="text",
                        text=json.dumps(formatted_pages, indent=2, ensure_ascii=False)
                    )
                ]
        except httpx.HTTPError as e:
            logger.error(f"Notion API error: {str(e)}")
            return [
                TextContent(
                    type="text",
                    text=f"Error listing pages: {str(e)}"
                )
            ]
    
    elif name == "notion_update_status":
        try:
            page_id = arguments.get("page_id")
            target_status = arguments.get("target_status")
            
            if not page_id or not target_status:
                return [
                    TextContent(
                        type="text",
                        text="Error: Both page_id and target_status are required."
                    )
                ]
            
            # Make API call to update the status
            async with httpx.AsyncClient() as client:
                response = await client.patch(
                    f"{NOTION_BASE_URL}/pages/{page_id}",
                    headers=headers,
                    json={
                        "properties": {
                            "Status": {
                                "status": {
                                    "name": target_status
                                }
                            }
                        }
                    }
                )
                response.raise_for_status()
                
                return [
                    TextContent(
                        type="text",
                        text=f"Successfully updated page status to '{target_status}'."
                    )
                ]
        except httpx.HTTPError as e:
            logger.error(f"Notion API error: {str(e)}")
            return [
                TextContent(
                    type="text",
                    text=f"Error updating status: {str(e)}\n" +
                         "Possible issues:\n" +
                         "1. Invalid page ID\n" +
                         "2. Invalid status value (must match one of the select options in your database)\n" +
                         "3. API permission issues (make sure your integration has write access)"
                )
            ]
    
    elif name == "notion_read_page_content":
        try:
            page_id = arguments.get("page_id")
            if not page_id:
                return [
                    TextContent(
                        type="text",
                        text="Error: page_id is required."
                    )
                ]
            
            page_data = await get_page_content(page_id)
            
            # Format the response in a readable way
            formatted_content = {
                "title": extract_text_from_title(page_data["properties"].get("Title", {})),
                "properties": {
                    k: format_property_value(v) 
                    for k, v in page_data["properties"].items()
                },
                "blocks": [format_block(block) for block in page_data["content"]]
            }
            
            return [
                TextContent(
                    type="text",
                    text=json.dumps(formatted_content, indent=2, ensure_ascii=False)
                )
            ]
        except httpx.HTTPError as e:
            logger.error(f"Notion API error: {str(e)}")
            return [
                TextContent(
                    type="text",
                    text=f"Error reading page content: {str(e)}"
                )
            ]
    
    elif name == "notion_update_page_content":
        try:
            page_id = arguments.get("page_id")
            content = arguments.get("content")
            
            if not page_id or not content:
                return [
                    TextContent(
                        type="text",
                        text="Error: Both page_id and content are required."
                    )
                ]

            # Convert content array to Notion blocks format
            blocks = [
                await create_block_content(block["type"], block["text"])
                for block in content
            ]
            
            # Update page content using Notion API
            async with httpx.AsyncClient() as client:
                response = await client.patch(
                    f"{NOTION_BASE_URL}/blocks/{page_id}/children",
                    headers=headers,
                    json={
                        "children": blocks
                    }
                )
                response.raise_for_status()
                
                return [
                    TextContent(
                        type="text",
                        text=f"Successfully updated page content with {len(blocks)} blocks."
                    )
                ]
        except httpx.HTTPError as e:
            logger.error(f"Notion API error: {str(e)}")
            return [
                TextContent(
                    type="text",
                    text=f"Error updating page content: {str(e)}"
                )
            ]
    
    elif name == "notion_add_comment":
        try:
            page_id = arguments.get("page_id")
            comment = arguments.get("comment")
            icon = arguments.get("icon", "💬")
            
            if not page_id or not comment:
                return [
                    TextContent(
                        type="text",
                        text="Error: Both page_id and comment are required."
                    )
                ]
            
            # Create a callout block for the comment
            comment_block = {
                "type": "callout",
                "object": "block",
                "callout": {
                    "rich_text": [{
                        "type": "text",
                        "text": {
                            "content": comment
                        }
                    }],
                    "icon": {
                        "type": "emoji",
                        "emoji": icon
                    },
                    "color": "gray_background"
                }
            }
            
            # Add the comment block to the page
            async with httpx.AsyncClient() as client:
                response = await client.patch(
                    f"{NOTION_BASE_URL}/blocks/{page_id}/children",
                    headers=headers,
                    json={
                        "children": [comment_block]
                    }
                )
                response.raise_for_status()
                
                return [
                    TextContent(
                        type="text",
                        text=f"Successfully added comment to the page."
                    )
                ]
        except httpx.HTTPError as e:
            logger.error(f"Notion API error: {str(e)}")
            return [
                TextContent(
                    type="text",
                    text=f"Error adding comment: {str(e)}"
                )
            ]
            
    else:
        raise ValueError(f"Unknown tool: {name}")

def extract_multi_select(property_data):
    """Extract values from a multi-select property"""
    if not property_data or property_data.get("type") != "multi_select":
        return []
    
    return [item.get("name", "") for item in property_data.get("multi_select", [])]

def extract_select(property_data):
    """Extract value from a select property"""
    if not property_data or property_data.get("type") != "select":
        return ""
    
    select_data = property_data.get("select", {})
    return select_data.get("name", "") if select_data else ""

def extract_text_from_title(title_property):
    """Extract text from title property"""
    if not title_property:
        return ""
    title_parts = title_property.get("title", [])
    return " ".join([part.get("plain_text", "") for part in title_parts]) if title_parts else ""

def format_property_value(property_data):
    """Format property value based on its type"""
    if not property_data:
        return None
    
    prop_type = property_data.get("type")
    if prop_type == "title":
        return extract_text_from_title(property_data)
    elif prop_type == "rich_text":
        return " ".join([part.get("plain_text", "") for part in property_data.get("rich_text", [])])
    elif prop_type == "select":
        select_data = property_data.get("select")
        return select_data.get("name") if select_data else None
    elif prop_type == "multi_select":
        return [item.get("name") for item in property_data.get("multi_select", [])]
    elif prop_type == "date":
        date_data = property_data.get("date", {})
        return {
            "start": date_data.get("start"),
            "end": date_data.get("end")
        } if date_data else None
    else:
        return property_data.get(prop_type)

def format_block(block):
    """Format block content based on its type"""
    block_type = block.get("type")
    if not block_type:
        return None
    
    content = block.get(block_type, {})
    if block_type in ["paragraph", "heading_1", "heading_2", "heading_3"]:
        return {
            "type": block_type,
            "text": " ".join([
                text.get("plain_text", "")
                for text in content.get("rich_text", [])
            ])
        }
    elif block_type == "bulleted_list_item" or block_type == "numbered_list_item":
        return {
            "type": block_type,
            "text": " ".join([
                text.get("plain_text", "")
                for text in content.get("rich_text", [])
            ])
        }
    else:
        return {
            "type": block_type,
            "content": content
        }

async def create_block_content(block_type: str, text: str) -> dict:
    """Create a block content structure for Notion API"""
    return {
        "type": block_type,
        "object": "block",
        block_type: {
            "rich_text": [
                {
                    "type": "text",
                    "text": {
                        "content": text
                    }
                }
            ]
        }
    }

async def main():
    """Main entry point for the server"""
    from mcp.server.stdio import stdio_server
    
    if not NOTION_API_KEY or not DATABASE_ID:
        raise ValueError("NOTION_API_KEY and NOTION_DATABASE_ID environment variables are required")
    
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options()
        )

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())