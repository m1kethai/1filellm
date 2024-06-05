import requests
from bs4 import BeautifulSoup, Comment
from urllib.parse import urljoin, urlparse
from PyPDF2 import PdfReader
from dotenv import load_dotenv
import os
import sys
import tiktoken
import nltk
from nltk.corpus import stopwords
import re
from pathlib import Path
import nbformat
from nbconvert import PythonExporter
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api.formatters import TextFormatter
import pyperclip
import wget
from tqdm import tqdm
from time import sleep
from rich import print
from rich.console import Console
from rich.panel import Panel
from rich.text import Text
from rich.prompt import Prompt
from rich.style import Style
from rich.syntax import Syntax
from rich.traceback import install
from rich.progress import Progress, TextColumn, BarColumn, TimeRemainingColumn

### FLAGS ###
enable_clipboard = False

console = Console()
allowed_extensions = []
exclude_paths = []

def set_filters():
    _allowed = []
    ext_categories = {
        "c_like":    { "ext_list": ['.c', '.h'], "enabled": 1 },
        "web":       { "ext_list": ['.html', '.css', '.js', '.ts', '.tsx'], "enabled": 1 },
        "data":      { "ext_list": ['.csv', '.json', '.jsonl', '.toml', '.yaml'], "enabled": 1 },
        "python":    { "ext_list": ['.py', '.pyx', '.ipynb'], "enabled": 1 },
        "scripting": { "ext_list": ['.sh', '.cjs'], "enabled": 1 },
        "rust":      { "ext_list": ['.rs'], "enabled": 1 },
        "markdown":  { "ext_list": ['.md'], "enabled": 1 },
        "sql":       { "ext_list": ['.sql'], "enabled": 1 },
        "config":    { "ext_list": ['.env', '.env.example', '.example'], "enabled": 1 },
        "misc":      { "ext_list": ['.localhost', '.txt'], "enabled": 1 }
    }

    for cat, data in ext_categories.items():
        if data["enabled"]:
            _allowed.extend(data["ext_list"])
            _allowed = sorted(_allowed)
            allowed_extensions.extend(_allowed)
            console.print(f"Enabled: {cat} ({data['ext_list']})", style="bold green")

    # Define path exclude patterns
    exclude_paths.extend([
        re.compile(r'.*pip.*'),
        re.compile(r'.*_internal.*'),
        re.compile(r'\.env|\.venv|venv'),
        re.compile(r'\.git|\.vscode|\.*cache.*|.*__pycache__.*|.*node_modules.*|.*dist.*|.*build.*|.*logs.*|.*tmp.*|.*temp')
    ])

def should_exclude(dir_name):
    for pattern in exclude_paths:
        if pattern.search(dir_name):
            return True
    return False

def is_allowed_filetype(filename):
    # ex. scenario: include all '.txt' files except for 'output.txt' or 'log.txt'
    excluded_extensions = ['.output.txt', '.log.txt']
    for ext in excluded_extensions:
        if filename.endswith(ext):
            console.print(f"Excluded: {filename} ({ext})", style="bold red")
            return False

    for ext in allowed_extensions:
        if filename.endswith(ext):
            return True

    ext = filename.split('.')[-1] if '.' in filename else 'no_extension'
    return False

def safe_file_read(filepath, fallback_encoding="latin1"):
    try:
        with open(filepath, "r", encoding="utf-8") as file:
            return file.read()
    except UnicodeDecodeError:
        with open(filepath, "r", encoding=fallback_encoding) as file:
            return file.read()

nltk.download("stopwords", quiet=True)
stop_words = set(stopwords.words("english"))

def github_auth_headers():
    # Get GitHub token from environment or local .env
    load_dotenv()
    TOKEN = os.getenv("GITHUB_TOKEN")
    if not TOKEN:
        raise EnvironmentError("GITHUB_TOKEN isn't set!")
    return {"Authorization": f"token {TOKEN}"}

def download_file(url, target_path):
    headers = github_auth_headers()
    response = requests.get(url, headers=headers)
    response.raise_for_status()
    with open(target_path, "wb") as f:
        f.write(response.content)

def process_ipynb_file(temp_file):
    with open(temp_file, "r", encoding="utf-8", errors="ignore") as f:
        notebook_content = f.read()

    exporter = PythonExporter()
    python_code, _ = exporter.from_notebook_node(
        nbformat.reads(notebook_content, as_version=4)
    )
    return python_code

def process_github_repo_directory(url, output):
    headers = github_auth_headers()
    response = requests.get(url, headers=headers)
    response.raise_for_status()
    files = response.json()

    for file in files:
        if file["type"] == "file" and is_allowed_filetype(file["name"]):
            console.print(f"Processing {file['path']}...", style="bold blue")

            temp_file = f"temp_{file['name']}"
            download_file(file["download_url"], temp_file)

            output.write(f"# {'-' * 10}\n")
            output.write(f"# Filename: {file['path']}\n")
            output.write(f"# {'-' * 10}\n\n")

            if file["name"].endswith(".ipynb"):
                output.write(process_ipynb_file(temp_file))
            else:
                with open(temp_file, "r", encoding="utf-8", errors="ignore") as f:
                    output.write(f.read())
            # output.write(f"\n")
            os.remove(temp_file)

        elif file["type"] == "dir":
            process_github_repo_directory(file["url"], output)

def process_local_dir_files(root, files, output):
    for file in files:
        file_path = os.path.join(root, file)
        if is_allowed_filetype(file_path):
            console.print(f"Processing: {file_path}", style="bold blue")

            output.write(f"#{'#' * 10}\n")
            output.write(f"# FILE - {file_path}:\n")
            output.write(f"#{'#' * 10}\n\n")

            if file_path.endswith(".ipynb"):
                output.write(process_ipynb_file(file_path))
            else:
                with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                    output.write(f.read())
            output.write("\n")

def process_local_directory(local_path, output):
    root_dir = local_path

    for root, dirs, files in os.walk(local_path):
        if root == root_dir:
            process_local_dir_files(root, files, output)
        else:
            if should_exclude(root):
                console.print(f"Excluding path: {root}", style="bold red")
                dirs[:] = [] # Clear the dirs list to skip processing subdirectories
                continue
            else:
                console.print(f"Including path: {root}", style="bold green")
                process_local_dir_files(root, files, output)
                for dir in dirs:
                    dir_path = os.path.join(root, dir)
                    if should_exclude(dir_path):
                        console.print(f"Excluding sub-path: '{dir_path}'", style="bold red")
                        dirs.remove(dir) # Remove the directory to skip processing its contents
                    else:
                        process_local_dir_files(dir_path, os.listdir(dir_path), output)

def process_github_repo(repo_url):
    headers = github_auth_headers()
    api_base_url = "https://api.github.com/repos/"
    repo_url_parts = repo_url.split("https://github.com/")[-1].split("/")
    repo_name = "/".join(repo_url_parts[:2])

    subdirectory = ""
    if len(repo_url_parts) > 4 and repo_url_parts[2] == "tree":
        subdirectory = "/".join(repo_url_parts[4:])

    contents_url = f"{api_base_url}{repo_name}/contents"
    if subdirectory:
        contents_url = f"{contents_url}/{subdirectory}"

    repo_content = []

    def process_github_repo_directory(url, repo_content):
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        files = response.json()

        for file in files:
            if file["type"] == "file" and is_allowed_filetype(file["name"]):
                console.print(f"Processing {file['path']}...", style="bold blue")

                temp_file = f"temp_{file['name']}"
                download_file(file["download_url"], temp_file)

                repo_content.append(f"# {'-' * 3}\n")
                repo_content.append(f"# Filename: {file['path']}\n")
                repo_content.append(f"# {'-' * 3}\n\n")

                if file["name"].endswith(".ipynb"):
                    repo_content.append(process_ipynb_file(temp_file))
                else:
                    with open(temp_file, "r", encoding="utf-8", errors="ignore") as f:
                        repo_content.append(f.read())

                repo_content.append("\n\n")
                os.remove(temp_file)
            elif file["type"] == "dir":
                process_github_repo_directory(file["url"], repo_content)

    process_github_repo_directory(contents_url, repo_content)

    console.print("\nAll files processed.\n", style="bold green")
    return "\n".join(repo_content)

def process_local_folder(local_path, output_file):
    with open(output_file, "w", encoding="utf-8") as output:
        process_local_directory(local_path, output)

    console.print("\nAll files processed.\n", style="bold green")

def process_arxiv_pdf(arxiv_abs_url, output_file):
    pdf_url = arxiv_abs_url.replace("/abs/", "/pdf/") + ".pdf"
    response = requests.get(pdf_url)
    pdf_content = response.content

    with open("temp.pdf", "wb") as pdf_file:
        pdf_file.write(pdf_content)

    text = []
    with open("temp.pdf", "rb") as pdf_file:
        pdf_reader = PdfReader(pdf_file)
        for page in range(len(pdf_reader.pages)):
            text.append(pdf_reader.pages[page].extract_text())

    with open(output_file, "w", encoding="utf-8") as output:
        output.write(" ".join(text))

    console.print("\nAll files processed.\n", style="bold green")

def extract_links(input_file, output_file):
    url_pattern = re.compile(
        r"http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+"
    )

    with open(input_file, "r", encoding="utf-8") as file:
        content = file.read()
        urls = re.findall(url_pattern, content)

    with open(output_file, "w", encoding="utf-8") as output:
        for url in urls:
            output.write(url + "\n")

def fetch_youtube_transcript(url):
    def extract_video_id(url):
        pattern = r"(?:https?:\/\/)?(?:www\.)?(?:youtube\.com\/(?:[^\/\n\s]+\/\S+\/|(?:v|e(?:mbed)?)\/|\S*?[?&]v=)|youtu\.be\/)([a-zA-Z0-9_-]{11})"
        match = re.search(pattern, url)
        if match:
            return match.group(1)
        return None

    video_id = extract_video_id(url)
    if not video_id:
        return "Error: Could not extract video ID from URL."

    try:
        transcript_list = YouTubeTranscriptApi.get_transcript(video_id)
        formatter = TextFormatter()
        transcript = formatter.format_transcript(transcript_list)
        return transcript
    except Exception as e:
        return f"Error: {str(e)}"

def preprocess_text(input_file, output_file):
    with open(input_file, "r", encoding="utf-8") as input_file:
        input_text = input_file.read()

    text = re.sub(r"[\n\r]+", "\n", input_text)
    text = re.sub(r"[^a-zA-Z0-9\s_.,!?:;@#$%^&*()+\-=[\]{}|\\<>`~'\"/]+", "", text)
    text = re.sub(r"\s+", " ", text)
    text = text.lower()

    words = text.split()
    words = [word for word in words if word not in stop_words]
    text = " ".join(words)

    with open(output_file, "w", encoding="utf-8") as output_file:
        output_file.write(text.strip())

def get_token_count(text):
    enc = tiktoken.get_encoding("cl100k_base")
    disallowed_special = enc.special_tokens_set - {""}
    tokens = enc.encode(text, disallowed_special=disallowed_special)
    return len(tokens)

def is_same_domain(base_url, new_url):
    return urlparse(base_url).netloc == urlparse(new_url).netloc

def is_within_depth(base_url, current_url, max_depth):
    base_parts = urlparse(base_url).path.rstrip("/").split("/")
    current_parts = urlparse(current_url).path.rstrip("/").split("/")

    if current_parts[: len(base_parts)] != base_parts:
        return False

    return len(current_parts) - len(base_parts) <= max_depth

def process_pdf(url):
    response = requests.get(url)
    response.raise_for_status()

    with open("temp.pdf", "wb") as pdf_file:
        pdf_file.write(response.content)

    text = []
    with open("temp.pdf", "rb") as pdf_file:
        pdf_reader = PdfReader(pdf_file)
        for page in range(len(pdf_reader.pages)):
            text.append(pdf_reader.pages[page].extract_text())

    os.remove("temp.pdf")
    return " ".join(text)

def crawl_and_extract_text(
    base_url, output_file, urls_list_file, max_depth, include_pdfs, ignore_epubs
):
    visited_urls = set()
    urls_to_visit = [(base_url, 0)]
    processed_urls = []
    all_text = ""

    while urls_to_visit:
        current_url, current_depth = urls_to_visit.pop(0)
        clean_url = current_url.split("#")[0]

        if (
            clean_url not in visited_urls
            and is_same_domain(base_url, clean_url)
            and is_within_depth(base_url, clean_url, max_depth)
        ):
            if ignore_epubs and clean_url.endswith(".epub"):
                continue

            try:
                response = requests.get(current_url)
                soup = BeautifulSoup(response.content, "html.parser")
                visited_urls.add(clean_url)

                if clean_url.endswith(".pdf") and include_pdfs:
                    text = process_pdf(clean_url)
                else:
                    for element in soup(
                        ["script", "style", "head", "title", "meta", "[document]"]
                    ):
                        element.decompose()
                    comments = soup.find_all(
                        string=lambda text: isinstance(text, Comment)
                    )
                    for comment in comments:
                        comment.extract()
                    text = soup.get_text(separator="\n", strip=True)

                all_text += f"\n\n# URL: {clean_url}\n{text}"
                processed_urls.append(clean_url)
                console.print(f"Processed: {clean_url}", style="bold blue")

                if current_depth < max_depth:
                    for link in soup.find_all("a", href=True):
                        new_url = urljoin(current_url, link["href"]).split("#")[0]
                        if (
                            new_url not in visited_urls
                            and is_within_depth(base_url, new_url, max_depth)
                            and (include_pdfs or not new_url.endswith(".pdf"))
                            and not (ignore_epubs and new_url.endswith(".epub"))
                        ):
                            urls_to_visit.append((new_url, current_depth + 1))

            except requests.RequestException as e:
                console.print(f"Failed to retrieve {clean_url}: {e}", style="bold red")

    processed_urls_string = "\n".join(processed_urls)
    header = f"Generated text from the website: {base_url}. This includes content from the base page and all linked pages up to {max_depth} levels deep.\nProcessed URLs:\n{processed_urls_string}\n\n"

    all_text = header + all_text

    with open(output_file, "w", encoding="utf-8") as file:
        file.write(all_text)

    with open(urls_list_file, "w", encoding="utf-8") as urls_file:
        for url in processed_urls:
            urls_file.write(url + "\n")

    return all_text

def process_doi_or_pmid(identifier, output_file):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 6.3) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/98.0.4758.102 Safari/537.36",
        "Connection": "keep-alive",
    }

    try:
        payload = {"sci-hub-plugin-check": "", "request": identifier}

        base_url = "https://sci-hub.se/"
        response = requests.post(base_url, headers=headers, data=payload, timeout=60)
        soup = BeautifulSoup(response.content, "html.parser")
        pdf_element = soup.find(id="pdf")

        if pdf_element is None:
            raise ValueError(
                f"No PDF found for identifier {identifier}. Sci-hub might be inaccessible or the document is not available."
            )

        content = (
            pdf_element.get("src")
            .replace("#navpanes=0&view=FitH", "")
            .replace("//", "/")
        )

        if content.startswith("/downloads"):
            pdf_url = "https://sci-hub.se" + content
        elif content.startswith("/tree"):
            pdf_url = "https://sci-hub.se" + content
        elif content.startswith("/uptodate"):
            pdf_url = "https://sci-hub.se" + content
        else:
            pdf_url = "https:/" + content

        pdf_filename = f"{identifier.replace('/', '-')}.pdf"
        wget.download(pdf_url, pdf_filename)

        with open(pdf_filename, "rb") as pdf_file:
            pdf_reader = PdfReader(pdf_file)
            text = ""
            for page in range(len(pdf_reader.pages)):
                text += pdf_reader.pages[page].extract_text()

        with open(output_file, "w", encoding="utf-8") as output:
            output.write(text)

        os.remove(pdf_filename)
        console.print(f"Identifier {identifier} processed successfully.", style="bold green")
    except (requests.RequestException, ValueError) as e:
        console.print(f"Error processing identifier {identifier}: {str(e)}", style="bold red")
        console.print("Sci-hub appears to be inaccessible or the document was not found. Please try again later.", style="bold yellow")

def process_github_pull_request(pull_request_url, output_file):
    # Extract repository owner, repository name, and pull request number from the URL
    url_parts = pull_request_url.split("/")
    repo_owner = url_parts[3]
    repo_name = url_parts[4]
    pull_request_number = url_parts[-1]

    # Make API requests to retrieve pull request information
    api_base_url = f"https://api.github.com/repos/{repo_owner}/{repo_name}/pulls/{pull_request_number}"
    headers = github_auth_headers()

    # Retrieve pull request details
    response = requests.get(api_base_url, headers=headers)
    pull_request_data = response.json()

    # Retrieve pull request diff
    diff_url = pull_request_data["diff_url"]
    diff_response = requests.get(diff_url, headers=headers)
    pull_request_diff = diff_response.text

    # Retrieve pull request comments and review comments
    comments_url = pull_request_data["comments_url"]
    review_comments_url = pull_request_data["review_comments_url"]
    comments_response = requests.get(comments_url, headers=headers)
    review_comments_response = requests.get(review_comments_url, headers=headers)
    comments_data = comments_response.json()
    review_comments_data = review_comments_response.json()

    # Combine comments and review comments into a single list
    all_comments = comments_data + review_comments_data

    # Sort comments based on their position in the diff
    all_comments.sort(key=lambda comment: comment.get("position") or float("inf"))

    # Format the retrieved pull request information
    formatted_text = f"# Pull Request Information\n\n"
    formatted_text += f"## Title: {pull_request_data['title']}\n\n"
    formatted_text += f"## Description:\n{pull_request_data['body']}\n\n"
    formatted_text += f"## Merge Details:\n"
    formatted_text += f"{pull_request_data['user']['login']} wants to merge {pull_request_data['commits']} commit into {repo_owner}:{pull_request_data['base']['ref']} from {pull_request_data['head']['label']}\n\n"
    formatted_text += f"## Diff and Comments:\n"

    # Iterate through the diff and interleave comments
    diff_lines = pull_request_diff.split("\n")
    comment_index = 0
    for line in diff_lines:
        formatted_text += f"{line}\n"
        while comment_index < len(all_comments) and all_comments[comment_index].get(
            "position"
        ) == diff_lines.index(line):
            comment = all_comments[comment_index]
            formatted_text += f"\n### Review Comment by {comment['user']['login']}:\n"
            formatted_text += f"{comment['body']}\n\n"
            formatted_text += f"Path: {comment['path']}\n"
            formatted_text += f"Line: {comment['original_line']}\n\n"
            comment_index += 1

    # Process the entire repository
    repo_url = f"https://github.com/{repo_owner}/{repo_name}"
    repo_content = process_github_repo(repo_url)

    # Concatenate the pull request information and repository content
    final_output = f"{formatted_text}\n\n# Repository Content\n\n{repo_content}"

    # Write the final output to the file
    with open(output_file, "w", encoding="utf-8") as file:
        file.write(final_output)

    console.print(f"Pull request {pull_request_number} and repository content processed successfully.", style="bold green")

    return final_output

def process_github_issue(issue_url, output_file):
    # Extract repository owner, repository name, and issue number from the URL
    url_parts = issue_url.split("/")
    repo_owner = url_parts[3]
    repo_name = url_parts[4]
    issue_number = url_parts[-1]

    # Make API requests to retrieve issue information
    api_base_url = (
        f"https://api.github.com/repos/{repo_owner}/{repo_name}/issues/{issue_number}"
    )
    headers = github_auth_headers()

    # Retrieve issue details
    response = requests.get(api_base_url, headers=headers)
    issue_data = response.json()

    # Retrieve issue comments
    comments_url = issue_data["comments_url"]
    comments_response = requests.get(comments_url, headers=headers)
    comments_data = comments_response.json()

    # Format the retrieved issue information
    formatted_text = f"# Issue Information\n\n"
    formatted_text += f"## Title: {issue_data['title']}\n\n"
    formatted_text += f"## Description:\n{issue_data['body']}\n\n"
    formatted_text += f"## Comments:\n"

    for comment in comments_data:
        formatted_text += f"\n### Comment by {comment['user']['login']}:\n"
        formatted_text += f"{comment['body']}\n"

        # Extract code snippets from comment
        code_snippets = re.findall(r"https://github.com/.*#L\d+-L\d+", comment["body"])
        for snippet_url in code_snippets:
            # Extract file path, start line, and end line from the snippet URL
            url_parts = snippet_url.split("#")
            file_url = url_parts[0].replace("/blob/", "/raw/")
            line_range = url_parts[1]
            start_line, end_line = map(int, line_range.split("-")[0][1:]), map(
                int, line_range.split("-")[1][1:]
            )

            # Make API request to retrieve the file content
            file_response = requests.get(file_url, headers=headers)
            file_content = file_response.text

            # Extract the code snippet based on the line range
            code_lines = file_content.split("\n")[start_line - 1 : end_line]
            code_snippet = "\n".join(code_lines)

            # Add the code snippet to the formatted text
            formatted_text += f"\n#### Code Snippet:\n```\n{code_snippet}\n```\n"

    # Process the entire repository
    repo_url = f"https://github.com/{repo_owner}/{repo_name}"
    repo_content = process_github_repo(repo_url)

    # Concatenate the issue information and repository content
    final_output = f"{formatted_text}\n\n# Repository Content\n\n{repo_content}"

    # Write the final output to the file
    with open(output_file, "w", encoding="utf-8") as file:
        file.write(final_output)

    console.print(f"Issue {issue_number} and repository content processed successfully.", style="bold green")

    return final_output

#! WIP - automatically restructure the 1st-pass content and remove useless/irrelevant/repetitive text
# def clean_and_restructure_content(content):
#     # Remove navigation and footer content
#     lines = content.split('\n')
#     cleaned_lines = []
#     for line in lines:
#         if 'Navigation' in line or 'index' in line or 'previous' in line or 'next' in line or '©' in line or 'Options' in line:
#             continue
#         cleaned_lines.append(line)

#     # Join the cleaned lines
#     cleaned_content = '\n'.join(cleaned_lines)
#     return cleaned_content
# # Clean and restructure the content
# cleaned_content = clean_and_restructure_content(content)

def main():
    intro_text = Text("Input Options:\n", style="dodger_blue1")
    input_types = [
        ("• Local Dir. Path\n", "bright_white"),
        ("• URL - GitHub", "bright_white"),
        ("  ⟹ Repository [Repo Contents]", "bright_white"),
        ("  ⟹ Pull Request [PR + Repo Contents]", "bright_white"),
        ("  ⟹ Issue [Issue + Repo Contents]", "bright_white"),
        ("\n• URL - Other", "bright_white"),
        ("  ⟹ Documentation (Docs Base URL)", "bright_white"),
        ("  ⟹ YouTube Video [Transcript]", "bright_white"),
        ("  ⟹ ArXiv Paper", "bright_white"),
        ("  ⟹ Sci-Hub Paper (DOI/PMID URL)", "bright_white"),
    ]

    for input_type, color in input_types:
        intro_text.append(f"\n{input_type}", style=color)

    intro_panel = Panel(
        intro_text,
        expand=False,
        border_style="bold",
        title="[bright_white]Path/URL Types[/bright_white]",
        title_align="center",
        padding=(1, 1),
    )
    console.print("\n")
    console.print(intro_panel)

    if len(sys.argv) > 1:
        input_path = sys.argv[1]
    else:
        input_path = Prompt.ask(
            "\n[bold dodger_blue1]Enter path or URL[/bold dodger_blue1]",
            console=console,
        )

    console.print(
        f"\n[bold bright_green]You entered:[/bold bright_green] [bold bright_yellow]{input_path}[/bold bright_yellow]"
    )

    output_dir = "output"
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
    output_file = os.path.join(output_dir, "uncompressed.output.txt")
    urls_list_file = os.path.join(output_dir, "processed_urls.txt")

    with Progress(
        TextColumn("[bold bright_blue]{task.description}"),
        BarColumn(bar_width=None),
        TimeRemainingColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("[bright_blue]Processing...", total=100)
        set_filters()

        if "github.com" in input_path:
            if "/pull/" in input_path:
                final_output = process_github_pull_request(input_path, output_file)
            elif "/issues/" in input_path:
                final_output = process_github_issue(input_path, output_file)
            else:
                repo_content = process_github_repo(input_path)
                with open(output_file, "w", encoding="utf-8") as file:
                    file.write(repo_content)
                final_output = repo_content
        elif urlparse(input_path).scheme in ["http", "https"]:
            if "youtube.com" in input_path or "youtu.be" in input_path:
                transcript = fetch_youtube_transcript(input_path)
                if transcript:
                    with open(output_file, "w", encoding="utf-8") as output:
                        output.write(f"# YouTube Video Transcript\n")
                        output.write(f"# URL: {input_path}\n\n")
                        output.write(transcript)
                    console.print(
                        "[bright_green]YouTube video transcript processed.[/bright_green]"
                    )
                else:
                    console.print(
                        "[bright_yellow]No transcript available for the YouTube video.[/bright_yellow]"
                    )
            elif "arxiv.org" in input_path:
                process_arxiv_pdf(input_path, output_file)
            else:
                final_output = crawl_and_extract_text(
                    input_path,
                    output_file,
                    urls_list_file,
                    max_depth=2,
                    include_pdfs=True,
                    ignore_epubs=True,
                )
        elif input_path.startswith("10.") and "/" in input_path or input_path.isdigit():
            process_doi_or_pmid(input_path, output_file)
        else:
            process_local_folder(input_path, output_file)

        progress.update(task, advance=50)

        processed_file = "compressed.output.txt"
        preprocess_text(output_file, processed_file)

        progress.update(task, advance=50)

    compressed_text = safe_file_read(processed_file)
    compressed_token_count = get_token_count(compressed_text)
    console.print(
        f"\n[bright_green]Compressed Token Count:[/bright_green] [bold bright_cyan]{compressed_token_count}[/bold bright_cyan]"
    )

    uncompressed_text = safe_file_read(output_file)
    uncompressed_token_count = get_token_count(uncompressed_text)
    console.print(
        f"[bright_green]Uncompressed Token Count:[/bright_green] [bold bright_cyan]{uncompressed_token_count}[/bold bright_cyan]"
    )

    console.print(
        f"\n[bold bright_yellow]compressed.output.txt[/bold bright_yellow] & [bold bright_blue]uncompressed.output.txt[/bold bright_blue] have been created in the working directory.\n"
    )

    if enable_clipboard:
        pyperclip.copy(uncompressed_text)
        console.print(
            f"[bright_white]The contents of [bold bright_blue]{output_file}[/bold bright_blue] have been copied to the clipboard.[/bright_white]\n"
        )

if __name__ == "__main__":
    main()
