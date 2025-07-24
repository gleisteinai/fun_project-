
import requests
import pdfplumber
import camelot
import json
import re
import time
import logging

API_URL = "https://api.together.xyz/v1/chat/completions"
API_KEY = "generate free api from togtherai"
MODEL = "meta-llama/Llama-3.3-70B-Instruct-Turbo-Free"
HEADERS = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json"
}

pdf_path = "yourfilepname or path"
output_json_path = "expected_output_testing1v59.json"

MAX_RETRIES = 3
PAGE_DELAY_SECONDS = 5

logging.basicConfig(filename="processing.log", level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logging.getLogger().addHandler(logging.StreamHandler())

data = {"pages": []}

def extract_text_from_page(page):
    return page.extract_text()

def clean_text(text):
    if not text:
        return ""
    text = text.replace("\u2019", "'").replace("\u2022", "-")
    text = re.sub(r'\s+', ' ', text).strip()
    return text

def generate_json_using_gpt(pdf_text, table_text):
    prompt = f"""
    Given the page text:
    {pdf_text}

    And extracted table content:
    {table_text}

    Generate JSON with titles, paragraphs, and disclaimers. Exclude any content that appears in the table to avoid duplication.

    Format:
    {{
        "pages": [{{
            "screen_id": "template_styles",
            "components": [
                {{ "type": "title", "title": "Title Here" }},
                {{ "type": "paragraph", "title": "", "text": "Paragraph here..." }}
            ]
        }}]
    }}
    """

    payload = {
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.5,
        "max_tokens": 2500
    }

    try:
        response = requests.post(API_URL, headers=HEADERS, json=payload)
        if response.status_code == 200:
            return response
        else:
            logging.error(f"Together.ai API Error {response.status_code}: {response.text}")
            return None
    except Exception as e:
        logging.error(f"GPT error: {e}")
        return None

def extract_tables_with_camelot(pdf_path, page_number):
    tables = []
    table_text_content = ""
    try:
        tables_camelot = camelot.read_pdf(pdf_path, flavor='lattice', pages=str(page_number))
        if not tables_camelot or tables_camelot.n == 0:
            tables_camelot = camelot.read_pdf(pdf_path, flavor='stream', pages=str(page_number))

        for table in tables_camelot:
            table_data = {"rows": []}
            num_columns = len(table.df.columns) if not table.df.empty else 0
            if num_columns == 0:
                logging.warning(f"No columns detected in table on page {page_number}")
                continue

            for row_idx, row in enumerate(table.df.itertuples(index=False), 1):
                cells = []
                row_values = [str(cell).strip().replace("\n", " ") for cell in row]
                for col_idx in range(num_columns):
                    cell_text = row_values[col_idx] if col_idx < len(row_values) else ""
                    table_text_content += cell_text + " "
                    cells.append({
                        "column": col_idx + 1,
                        "text": cell_text,
                        "height_units": 1,
                        "width_units": 1
                    })
                table_data["rows"].append({"row": row_idx, "cells": cells})
            tables.append(table_data)

    except Exception as e:
        logging.error(f"Table extraction error page {page_number}: {e}")

    return tables, table_text_content.strip()

def save_json_to_file(data, file_path):
    try:
        if data["pages"]:
            with open(file_path, "w", encoding="utf-8") as json_file:
                json.dump(data, json_file, indent=4, ensure_ascii=False)
            logging.info(f"JSON saved: {file_path}")
        else:
            logging.warning("No data to save. Final JSON is empty.")
    except Exception as e:
        logging.error(f"Saving JSON error: {e}")

def process_large_pdf(pdf_path):
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for page_number in range(1, len(pdf.pages) + 1):
                logging.info(f"Processing page {page_number}")

                page = pdf.pages[page_number - 1]
                page_text = extract_text_from_page(page)

                if not page_text:
                    logging.warning(f"Empty text on page {page_number}")
                    continue

                cleaned_text = clean_text(page_text)
                tables_extracted, table_text = extract_tables_with_camelot(pdf_path, page_number)

                generated_json = None
                retries = 0
                while retries < MAX_RETRIES and not generated_json:
                    generated_json = generate_json_using_gpt(cleaned_text, table_text)
                    if not generated_json:
                        retries += 1
                        logging.info(f"Retrying GPT for page {page_number} (attempt {retries})")
                        time.sleep(5)

                if generated_json:
                    json_response = generated_json.json()
                    try:
                        content_str = json_response["choices"][0]["message"]["content"]

                        json_str = re.search(r'```json\s*(\{.*?\})\s*```', content_str, re.DOTALL)
                        if not json_str:
                            raise ValueError("No valid JSON block found in response content.")

                        parsed_json = json.loads(json_str.group(1))

                        if "pages" not in parsed_json or not parsed_json["pages"]:
                            logging.warning(f"GPT response contains no 'pages' key:\n{parsed_json}")
                            continue
                        
                        page_components = parsed_json["pages"][0]["components"]

                        for table in tables_extracted:
                            page_components.append({
                                "type": "table_general_purposes",
                                "table": table
                            })

                        data["pages"].append({
                            "screen_id": "template_styles",
                            "page_index": page_number,
                            "components": page_components
                        })

                    except Exception as e:
                        logging.error(f"Error extracting/parsing GPT response JSON on page {page_number}: {e}")
                        logging.debug(f"Full GPT raw response: {json_response}")
                else:
                    logging.warning(f"Skipping page {page_number} after max retries")

                logging.info(f"Completed page {page_number}. Sleeping {PAGE_DELAY_SECONDS}s...")
                time.sleep(PAGE_DELAY_SECONDS)

        save_json_to_file(data, output_json_path)

    except Exception as e:
        logging.error(f"Processing PDF error: {e}")

process_large_pdf(pdf_path)
