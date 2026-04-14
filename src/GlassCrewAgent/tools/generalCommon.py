import os
import shutil
import time

import fitz  # pymupdf
import requests
import feedparser
from crewai.tools import tool

# Common browser headers to avoid being blocked as a bot
DEFAULT_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.5',
    'Accept-Encoding': 'gzip, deflate, br',
    'Connection': 'keep-alive',
}

# Global rate limiting for arXiv API requests
_last_arxiv_request_time = 0
_min_request_interval = 3.0  # Minimum 3 seconds between requests to arXiv

def _wait_for_rate_limit():
    """Wait to ensure minimum interval between arXiv API requests"""
    import time
    global _last_arxiv_request_time
    now = time.time()
    elapsed = now - _last_arxiv_request_time
    if elapsed < _min_request_interval:
        sleep_time = _min_request_interval - elapsed
        time.sleep(sleep_time)
    _last_arxiv_request_time = time.time()

def download_pdf(url, filename, max_retries=4, initial_delay=5):
    """
    Download a PDF file from the specified URL to the given filename.
    Retries with exponential backoff when rate limited.
    
    Args:
        url (str): The URL of the PDF file to download.
        filename (str): The local path where the PDF will be saved.
        max_retries (int): Maximum number of retry attempts.
        initial_delay (int): Initial delay in seconds before first retry.
    
    Returns:
        bool: True if download succeeded, False otherwise.
    """
    session = requests.Session()
    delay = initial_delay
    
    for retry in range(max_retries):
        try:
            _wait_for_rate_limit()
            time.sleep(delay if retry > 0 else 2)  # First request has shorter delay
            response = session.get(url, headers=DEFAULT_HEADERS)
            
            if response.status_code == 200:
                with open(filename, 'wb') as f:
                    f.write(response.content)
                return True
            elif response.status_code == 429:
                # Rate limited, wait and retry
                print(f"Rate limited downloading PDF. Retrying in {delay * 2} seconds...")
                time.sleep(delay * 2)
                delay *= 2
                continue
            else:
                print(f"Failed to download {url}: Status code {response.status_code}")
        except Exception as e:
            print(f"Exception downloading {url}: {e}")
            if retry < max_retries - 1:
                time.sleep(delay)
                delay *= 2
    
    print(f"Failed to download {url} after {max_retries} retries")
    return False


def clear_directory(path):
    """
    Clear all files and subdirectories in the specified path.
    
    Args:
        path (str): The directory path to clear.
    
    Returns:
        None
    """
    for filename in os.listdir(path):
        file_path = os.path.join(path, filename)
        try:
            if os.path.isfile(file_path) or os.path.islink(file_path):
                os.unlink(file_path)
            elif os.path.isdir(file_path):
                shutil.rmtree(file_path)
        except Exception as e:
            print(f"Failed to delete {file_path}. Reason: {e}")


@tool("Download Papers from ArXiv (Single Keyword)")
def download_papers_from_arxiv_single(keyword: str, max_results: int = 3) -> str:
    """
    Download papers from arXiv based on a single keyword search query.
    
    This tool searches the arXiv API for papers matching the provided keyword,
    downloads the PDF files to a local directory, and returns the results
    in Markdown format with titles and URLs.
    
    Args:
        keyword (str): The keyword to search for in arXiv. Can be any research 
                       topic, author name, or topic of interest.
        max_results (int, optional): The maximum number of papers to download. 
                                   Defaults to 3.
    
    Returns:
        str: A Markdown formatted string containing the titles and URLs of 
              downloaded papers, or an error message if the download fails.
    
    Notes:
        - PDFs are saved to data/TempFiles/arxiv_pdf directory
        - Existing PDFs in the directory are cleared before downloading new ones
        - Uses arXiv API at http://export.arxiv.org/api/query
        - Title special characters (/ and :) are replaced with - for filename safety
    """
    # Convert string inputs to proper types (handles LLM outputting strings)
    def to_int(val):
        if val is None:
            return 3
        if isinstance(val, str):
            try:
                return int(val.strip())
            except ValueError:
                return 3
        return int(val)
    
    max_results = to_int(max_results)
    
    ARXIV_API_URL = "http://export.arxiv.org/api/query"

    query_params = {
        "search_query": f"all:{keyword}",
        "start": 0,
        "max_results": max_results
    }

    download_path = "data/TempFiles/arxiv_pdf"
    if os.path.exists(download_path) and os.listdir(download_path):
        clear_directory(download_path)
    else:
        os.makedirs(download_path, exist_ok=True)

    session = requests.Session()
    max_retries = 3
    initial_delay = 3
    
    try:
        delay = initial_delay
        success = False
        response = None
        
        for retry in range(max_retries):
            try:
                time.sleep(delay if retry > 0 else 3)  # Longer initial delay to be polite
                response = session.get(ARXIV_API_URL, params=query_params, headers=DEFAULT_HEADERS)
                response.raise_for_status()
                success = True
                break
            except requests.exceptions.RequestException as e:
                if response is not None and response.status_code == 429 and retry < max_retries - 1:
                    # Rate limited, back off exponentially
                    print(f"Rate limited by arXiv API. Retrying in {delay * 2} seconds... (Attempt {retry + 1}/{max_retries})")
                    time.sleep(delay)
                    delay *= 2
                else:
                    raise e
        
        if not success:
            return f"Error downloading papers: Failed after {max_retries} retries due to rate limiting. Try again later."
        
        feed = feedparser.parse(response.content)

        markdown_content = f"### Downloaded arXiv Papers (Keyword: `{keyword}`)\n\n"

        successful_downloads = 0
        for entry in feed.entries:
            title = entry.title.replace('/', '-').replace(':', '-')
            pdf_url = entry.link.replace("abs", "pdf") + ".pdf"
            filename = os.path.join(download_path, f"{title}.pdf")

            # Download the PDF file with retries
            if download_pdf(pdf_url, filename):
                successful_downloads += 1
                markdown_content += f"- **[{title}]({pdf_url})**\n"

        if successful_downloads == 0 and len(feed.entries) > 0:
            markdown_content += "\n*Note: All PDF downloads failed after retries. Only metadata is available.*\n"
        
        return markdown_content

    except requests.exceptions.RequestException as e:
        return f"Error downloading papers: {e}"


def _read_local_pdf(filename: str, directory: str = "data/TempFiles/arxiv_pdf") -> str:
    """Internal function to actually read the PDF"""
    # Handle case where full path is provided
    if os.path.isfile(filename):
        file_path = filename
    else:
        file_path = os.path.join(directory, filename)
    
    if not os.path.exists(file_path):
        return f"Error: File {file_path} does not exist. Use list_downloaded_pdfs to see available PDFs."
    
    if not filename.lower().endswith('.pdf'):
        return f"Error: {file_path} is not a PDF file."
    
    try:
        doc = fitz.open(file_path)
        text_content = []
        total_pages = doc.page_count
        
        for page_num in range(total_pages):
            page = doc.load_page(page_num)
            text = page.get_text()
            if text.strip():
                text_content.append(text)
        
        doc.close()
        
        full_text = "\n\n".join(text_content)
        
        if not full_text.strip():
            return f"Warning: No text content extracted from {file_path}. The PDF may be scanned/image-only."
        
        # Add header with metadata
        result = f"### PDF Content: {os.path.basename(file_path)}\n\n"
        result += f"**Pages:** {total_pages}\n"
        result += f"**File Size:** {os.path.getsize(file_path):,} bytes\n\n"
        result += "---\n\n"
        result += full_text
        
        # Truncate if extremely large to avoid context issues
        if len(result) > 100000:
            result = result[:100000] + f"\n\n... [Content truncated due to length - total length was {len(result):,} characters]"
        
        return result
        
    except Exception as e:
        return f"Error reading PDF {file_path}: {str(e)}"


@tool("List Downloaded PDFs")
def list_downloaded_pdfs() -> str:
    """
    List all PDF files that have been downloaded to the local arXiv directory.
    This tool helps the agent know which PDFs are available for reading.
    
    Returns:
        str: A Markdown formatted list of all available PDF filenames.
             Returns an error message if the directory doesn't exist or is empty.
    """
    download_path = "data/TempFiles/arxiv_pdf"
    
    if not os.path.exists(download_path):
        return f"Directory {download_path} does not exist. No PDFs have been downloaded yet."
    
    pdf_files = [f for f in os.listdir(download_path) if f.lower().endswith('.pdf')]
    
    if not pdf_files:
        return f"No PDF files found in {download_path}. Please download some papers first using download_papers_from_arxiv tools."
    
    markdown_content = f"### Available Downloaded PDF Files ({len(pdf_files)} files):\n\n"
    for i, filename in enumerate(pdf_files, 1):
        markdown_content += f"{i}. `{filename}`\n"
    
    markdown_content += f"\nUse `read_local_pdf` with the filename to read the full content of any PDF."
    return markdown_content


@tool("Read Local PDF")
def read_local_pdf(filename: str, directory: str = "data/TempFiles/arxiv_pdf") -> str:
    """
    Read a local PDF file and extract its full text content.
    This tool extracts all text from a PDF file on disk and returns it to the agent.
    
    Args:
        filename (str): The name of the PDF file to read.
                       Can be just the filename if it's in the default arXiv directory,
                       or full path if it's in a different location.
        directory (str, optional): The directory where the PDF is located. 
                                  Defaults to "data/TempFiles/arxiv_pdf".
    
    Returns:
        str: The full text content extracted from the PDF, or an error message 
             if the file cannot be read or doesn't exist.
    """
    return _read_local_pdf(filename, directory)


@tool("Read All Downloaded PDFs")
def read_all_downloaded_pdfs() -> str:
    """
    Read all PDF files in the default downloaded arXiv papers directory and return their combined text content.
    This tool allows the agent to read all downloaded papers at once.
    
    Returns:
        str: Combined text content from all available PDF files, separated by document boundaries.
    """
    download_path = "data/TempFiles/arxiv_pdf"
    
    if not os.path.exists(download_path):
        return f"Directory {download_path} does not exist. No PDFs have been downloaded yet."
    
    pdf_files = [f for f in os.listdir(download_path) if f.lower().endswith('.pdf')]
    
    if not pdf_files:
        return f"No PDF files found in {download_path}. Please download some papers first using download_papers_from_arxiv tools."
    
    all_content = f"# Combined Content of All Downloaded PDFs ({len(pdf_files)} documents)\n\n"
    
    for filename in pdf_files:
        content = _read_local_pdf(filename, download_path)
        if content.startswith("Error:") or content.startswith("Warning: No text"):
            # Skip errors or empty content
            continue
        all_content += content
        all_content += "\n\n" + "=" * 80 + "\n\n"
    
    if len(all_content) > 200000:
        all_content = all_content[:200000] + "\n\n... [Content truncated due to overall length]"
    
    return all_content


@tool("Search ArXiv Papers (Single Keyword) - with Abstract")
def search_arxiv_papers_single(keyword: str, max_results: int = 5) -> str:
    """
    Search arXiv for papers matching a single keyword and return their abstracts.
    This tool does not download PDF files, it only retrieves metadata and abstracts.
    
    Args:
        keyword (str): The keyword to search for in arXiv.
        max_results (int, optional): Maximum number of results to return. Defaults to 5.
    
    Returns:
        str: Markdown formatted results with titles, authors, dates, and abstracts.
    """
    # Convert string inputs to proper types (handles LLM outputting strings)
    def to_int(val):
        if val is None:
            return 5
        if isinstance(val, str):
            try:
                return int(val.strip())
            except ValueError:
                return 5
        return int(val)
    
    max_results = to_int(max_results)
    
    ARXIV_API_URL = "http://export.arxiv.org/api/query"

    query_params = {
        "search_query": f"all:{keyword}",
        "start": 0,
        "max_results": max_results
    }

    session = requests.Session()
    max_retries = 4
    initial_delay = 5
    
    try:
        delay = initial_delay
        success = False
        response = None
        
        for retry in range(max_retries):
            try:
                _wait_for_rate_limit()
                time.sleep(delay if retry > 0 else 3)  # Longer initial delay to be polite
                response = session.get(ARXIV_API_URL, params=query_params, headers=DEFAULT_HEADERS)
                response.raise_for_status()
                success = True
                break
            except requests.exceptions.RequestException as e:
                if response is not None and response.status_code == 429 and retry < max_retries - 1:
                    print(f"Rate limited by arXiv API. Retrying in {delay * 2} seconds... (Attempt {retry + 1}/{max_retries})")
                    time.sleep(delay)
                    delay *= 2
                else:
                    raise e
        
        if not success:
            return f"Error searching papers: Failed after {max_retries} retries due to rate limiting"
        
        feed = feedparser.parse(response.content)

        if not feed.entries:
            return f"No papers found for keyword: `{keyword}`"

        markdown_content = f"### arXiv Search Results (Keyword: `{keyword}`, {len(feed.entries)} papers)\n\n"

        for i, entry in enumerate(feed.entries, 1):
            title = entry.title
            authors = ", ".join([author.name for author in entry.authors]) if 'authors' in entry else "Unknown authors"
            published = entry.published if 'published' in entry else "Unknown date"
            summary = entry.summary if 'summary' in entry else "No abstract available"
            link = entry.link
            
            markdown_content += f"---\n"
            markdown_content += f"**{i}. [{title}]({link})**\n\n"
            markdown_content += f"**Authors:** {authors}\n\n"
            markdown_content += f"**Published:** {published}\n\n"
            markdown_content += f"**Abstract:**\n\n{summary}\n\n"

        return markdown_content

    except requests.exceptions.RequestException as e:
        return f"Error searching papers: {e}"


@tool("Search ArXiv Papers (Multiple Keywords) - with Abstract")
def search_arxiv_papers(keywords_str: str, max_results: int = 5) -> str:
    """
    Search arXiv for papers matching multiple keywords (AND logic) and return their abstracts.
    This tool does not download PDF files, it only retrieves metadata and abstracts.
    
    Args:
        keywords_str (str): Comma-separated string of keywords (all keywords must match).
        max_results (int, optional): Maximum number of results to return. Defaults to 5.
    
    Returns:
        str: Markdown formatted results with titles, authors, dates, and abstracts.
    """
    # Convert string inputs to proper types (handles LLM outputting strings)
    def to_int(val):
        if val is None:
            return 5
        if isinstance(val, str):
            try:
                return int(val.strip())
            except ValueError:
                return 5
        return int(val)
    
    max_results = to_int(max_results)
    
    ARXIV_API_URL = "http://export.arxiv.org/api/query"

    keywords = [keyword.strip() for keyword in keywords_str.split(',') if keyword.strip()]
    joined_keywords = " AND ".join(f"all:{keyword}" for keyword in keywords)
    
    query_params = {
        "search_query": joined_keywords,
        "start": 0,
        "max_results": max_results
    }

    session = requests.Session()
    max_retries = 4
    initial_delay = 5
    
    try:
        delay = initial_delay
        success = False
        response = None
        
        for retry in range(max_retries):
            try:
                _wait_for_rate_limit()
                time.sleep(delay if retry > 0 else 3)
                response = session.get(ARXIV_API_URL, params=query_params, headers=DEFAULT_HEADERS)
                response.raise_for_status()
                success = True
                break
            except requests.exceptions.RequestException as e:
                if response is not None and response.status_code == 429 and retry < max_retries - 1:
                    print(f"Rate limited by arXiv API. Retrying in {delay * 2} seconds... (Attempt {retry + 1}/{max_retries})")
                    time.sleep(delay)
                    delay *= 2
                else:
                    raise e
        
        if not success:
            return f"Error searching papers: Failed after {max_retries} retries due to rate limiting"
        
        feed = feedparser.parse(response.content)

        if not feed.entries:
            return f"No papers found for keywords: `{', '.join(keywords)}`"

        markdown_content = f"### arXiv Search Results (Keywords: `{', '.join(keywords)}`, {len(feed.entries)} papers)\n\n"

        for i, entry in enumerate(feed.entries, 1):
            title = entry.title
            authors = ", ".join([author.name for author in entry.authors]) if 'authors' in entry else "Unknown authors"
            published = entry.published if 'published' in entry else "Unknown date"
            summary = entry.summary if 'summary' in entry else "No abstract available"
            link = entry.link
            
            markdown_content += f"---\n"
            markdown_content += f"**{i}. [{title}]({link})**\n\n"
            markdown_content += f"**Authors:** {authors}\n\n"
            markdown_content += f"**Published:** {published}\n\n"
            markdown_content += f"**Abstract:**\n\n{summary}\n\n"

        return markdown_content

    except requests.exceptions.RequestException as e:
        return f"Error searching papers: {e}"
    

@tool("Download Papers from ArXiv (Multiple Keywords)")
def download_papers_from_arxiv(keywords_str: str, max_results: int = 5) -> str:
    """
    Download papers from arXiv based on multiple keywords combined with AND logic.
    
    This tool searches the arXiv API for papers matching all provided keywords,
    downloads the PDF files to a local directory, and returns the results
    in Markdown format with titles and URLs.
    
    Args:
        keywords_str (str): A comma-separated string of keywords to search for.
                           All keywords must be present in the paper (AND logic).
        max_results (int, optional): The maximum number of papers to download. 
                                   Defaults to 5.
    
    Returns:
        str: A Markdown formatted string containing the titles and URLs of 
              downloaded papers, or an error message if the download fails.
    
    Notes:
        - PDFs are saved to data/TempFiles/arxiv_pdf directory
        - Existing PDFs in the directory are cleared before downloading new ones
        - Uses arXiv API at http://export.arxiv.org/api/query
        - Keywords are combined using AND for more specific search results
        - Title special characters (/ and :) are replaced with - for filename safety
    """
    # Convert string inputs to proper types (handles LLM outputting strings)
    def to_int(val):
        if val is None:
            return 5
        if isinstance(val, str):
            try:
                return int(val.strip())
            except ValueError:
                return 5
        return int(val)
    
    max_results = to_int(max_results)
    
    ARXIV_API_URL = "http://export.arxiv.org/api/query"

    keywords = [keyword.strip() for keyword in keywords_str.split(',') if keyword.strip()]

    # Joining the keywords with 'AND' for the query
    joined_keywords = " AND ".join(f"all:{keyword}" for keyword in keywords)
    
    query_params = {
        "search_query": joined_keywords,
        "start": 0,
        "max_results": max_results
    }

    download_path = "data/TempFiles/arxiv_pdf"
    if os.path.exists(download_path) and os.listdir(download_path):
        clear_directory(download_path)
    else:
        os.makedirs(download_path, exist_ok=True)

    session = requests.Session()
    max_retries = 4
    initial_delay = 5
    
    try:
        delay = initial_delay
        success = False
        response = None
        
        for retry in range(max_retries):
            try:
                _wait_for_rate_limit()
                time.sleep(delay if retry > 0 else 3)  # Longer initial delay to be polite to arXiv
                response = session.get(ARXIV_API_URL, params=query_params, headers=DEFAULT_HEADERS)
                response.raise_for_status()
                success = True
                break
            except requests.exceptions.RequestException as e:
                if response is not None and response.status_code == 429 and retry < max_retries - 1:
                    # Rate limited, back off exponentially
                    print(f"Rate limited by arXiv API. Retrying in {delay * 2} seconds... (Attempt {retry + 1}/{max_retries})")
                    time.sleep(delay)
                    delay *= 2
                else:
                    raise e
        
        if not success:
            return f"Error downloading papers: Failed after {max_retries} retries due to rate limiting. Try again later."
        
        feed = feedparser.parse(response.content)

        markdown_content = f"### Downloaded arXiv Papers (Keywords: `{', '.join(keywords)}`)\n\n"

        successful_downloads = 0
        for entry in feed.entries:
            title = entry.title.replace('/', '-').replace(':', '-')
            pdf_url = entry.link.replace("abs", "pdf") + ".pdf"
            filename = os.path.join(download_path, f"{title}.pdf")

            # Download the PDF file with retries
            if download_pdf(pdf_url, filename):
                successful_downloads += 1
                markdown_content += f"- **[{title}]({pdf_url})**\n"

        if successful_downloads == 0 and len(feed.entries) > 0:
            markdown_content += "\n*Note: All PDF downloads failed after retries. Only metadata is available.*\n"
        
        return markdown_content

    except requests.exceptions.RequestException as e:
        return f"Error downloading papers: {e}"
