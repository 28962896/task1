import os 
from openai import OpenAI
import json 
from PyPDF2 import PdfReader
import time
from traceback import format_exc

POLICY_SUMMARY_USER_PROMPT = """
Please extract policy rules from the following policy documentation published by {country_code} (2-letter country code. EU means European Union). Each page is marked with '=== PAGE X ===':

{batch_text}

Please follow these rules when summarizing:
- If the text is not English, please translate the text to English before summarizing.
- Only inlcude rules that is related to cybercrime and the prevention, punishment and investigation of cybercrimes. If no cybercrime related policy rules are found, please return an empty cybercrime_related_policy_rules array.
- Do not omit any important information.
- If a policy rule covers multiple area, split it into multiple rules.
- If the given country is EU, use EU as country_code in response.
- Please respond in the following JSON example:

{response_schema}
"""


POLICY_SUMMARY_RESPONSE_SCHEMA = {
    "cybercrime_related_policy_rules": [
        {
            "country_code": "US",
            "rule_name": "Preventing DDoS attacks",
            "rule_content": "DDoS attacks are illegal and will be prosecuted",
            "additional_info": "The punishment for a DDoS attack can include a fine, prison time, and seizure of electronic devices. The severity of the punishment depends on the nature of the attack and the damage caused."
        }
    ]
}

def get_policy_pdfs_map()->dict:
    pdf_files_by_dir = {}
    
    for root, dirs, files in os.walk('./policies'):
        pdf_files = [os.path.join(root, file) for file in files if file.lower().endswith('.pdf')]
        if pdf_files:
            # Get subdirectory name relative to ./policies
            subdir = os.path.relpath(root, './policies')
            if subdir == '.':
                subdir = 'root'
            pdf_files_by_dir[subdir] = pdf_files
    
    return pdf_files_by_dir


def print_pdf_contents():
    pdf_files = get_policy_pdfs_map()
    
    for pdf_path in pdf_files[:1]:
        print(f"\nReading file: {pdf_path}")
        reader = PdfReader(pdf_path)
        
        for page_num in range(len(reader.pages)):
            page = reader.pages[page_num]
            print(f"\n--- Page {page_num + 1} ---")
            print(page.extract_text())


def get_combined_text(pages, max_words=2048):
    combined_text = ""
    page_markers = []
    
    for i, page in enumerate(pages):
        text = page.extract_text()
        if len(combined_text.split(" ")) + len(text.split(" ")) < max_words:
            page_markers.append(i + 1)
            combined_text += f"\n=== PAGE {i + 1} ===\n{text}"
        else:
            break
            
    return combined_text, page_markers

def summarize_pdfs():
    client = OpenAI(
        base_url="https://api.deepseek.com",
        api_key="sk-bc25f2bdae0b48f080f187ae944d78ce"
    )
    
    pdf_files_map = get_policy_pdfs_map()

    print(f"pdf_files_map: {pdf_files_map}")
    
    policy_rules_map = {}
    
    for country_code, pdf_paths in pdf_files_map.items():
        policy_rules_map[country_code] = []

        for pdf_path in pdf_paths:
            print(f"Processing {pdf_path}")

            reader = PdfReader(pdf_path)

            pages = reader.pages
            current_page = 0
            
            while current_page < len(pages):
                start_time = time.time()

                batch_text, page_numbers = get_combined_text(pages[current_page:])
                
                response = None 

                try:
                    response = client.chat.completions.create(
                        model="deepseek-chat",
                        messages=[
                            {
                                "role": "system",
                                "content": [{
                                    "type": "text",
                                    "text": "You are an expert in cybercrimes and global government policy-making."
                                }]
                            },
                            {
                                "role": "user",
                                "content": [{
                                    "type": "text",
                                    "text": POLICY_SUMMARY_USER_PROMPT.format(
                                        source_doc_name=os.path.basename(pdf_path),
                                        country_code=country_code,
                                        batch_text=batch_text,
                                        response_schema=POLICY_SUMMARY_RESPONSE_SCHEMA
                                    )
                                }]
                            }
                        ],
                        temperature=1,
                        max_tokens=4096,
                        top_p=1,
                        frequency_penalty=0,
                        presence_penalty=0,
                        response_format={
                            "type": "json_object",
                        }
                    )

                except Exception as e:
                    print(f"Error: {e}, {format_exc()}")
                    continue
                
                summary = response.choices[0].message.content

                print(f"Model response: {summary}")
                
                try:
                    summary_json = None

                    rules = []

                    if isinstance(summary, str):
                        summary = summary.replace("```json", "").replace("```", "")
                        summary_json = json.loads(summary)

                        rules = summary_json.get("cybercrime_related_policy_rules", [])
                        for r in rules:
                            r["from_doc"] = os.path.basename(pdf_path)

                    elif isinstance(summary, dict):
                        summary_json = summary

                    else:
                        print(f"Unexpected type for summary: {type(summary)}, {summary}")
                        continue

                    policy_rules_map[country_code].extend(rules)

                except json.JSONDecodeError:
                    print(f"Failed to parse JSON: {summary}")
                    continue
                
                
                current_page += len(page_numbers)

                print(f"Processed pages: {[p + current_page for p in page_numbers]} of {pdf_path} in {time.time() - start_time:.2f} seconds")

                with open("./policy_rules_by_country.json", "w+") as outfile:
                    json.dump(policy_rules_map, outfile, indent=2)



if __name__ == "__main__":
    summarize_pdfs()
