import os
import shutil

import requests
import feedparser
from paperqa import Docs
from crewai.tools import tool

from config import Config


def download_pdf(url, filename):
    """
    Download a PDF file from the specified URL to the given filename.
    
    Args:
        url (str): The URL of the PDF file to download.
        filename (str): The local path where the PDF will be saved.
    
    Returns:
        None
    """
    response = requests.get(url)
    if response.status_code == 200:
        with open(filename, 'wb') as f:
            f.write(response.content)
    else:
        print(f"Failed to download {url}")


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


@tool("Get Paper QA")
def get_paperqa(question: str) -> str:
    """
    Answer questions about papers using paperqa by querying PDF documents.
    
    This tool searches through downloaded PDF papers in the arxiv_pdf directory
    and provides answers to questions based on the content of those papers.
    It uses paperqa to perform retrieval-augmented question answering on the documents.
    
    Args:
        question (str): The question to ask about the papers. Should be related to 
                       the content of the downloaded PDF files.
    
    Returns:
        str: The answer to the question based on the paper content, or an error 
             message if no PDFs are found or processing fails.
    
    Notes:
        - Requires PDF files to be present in data/TempFiles/arxiv_pdf directory
        - Uses the configured LLM model from Config for question answering
        - The answer is formatted as a complete response with relevant citations
    """
    pdf_dir = "data/TempFiles/arxiv_pdf"
    
    # Check if the specified directory exists
    if not os.path.exists(pdf_dir):
        return "PDF directory does not exist."

    # Get all the PDF files in the directory
    pdf_files = [os.path.join(pdf_dir, f) for f in os.listdir(pdf_dir) if f.endswith('.pdf')]

    # Check if there are any PDF files
    if not pdf_files:
        return "No PDF files in the directory."

    # Initialize Docs object and add PDF documents
    try:
        docs = Docs(llm=Config().MODEL_NAME)

        for pdf_file in pdf_files:
            docs.add(pdf_file)

        answer = docs.query(question)
        return answer.formatted_answer
    except Exception as e:
        return f"Error occurred while processing PDF files: {e}"


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

    try:
        response = requests.get(ARXIV_API_URL, params=query_params)
        response.raise_for_status()  # Check if the request was successful
        feed = feedparser.parse(response.content)

        markdown_content = f"### Downloaded arXiv Papers (Keyword: `{keyword}`)\n\n"

        for entry in feed.entries:
            title = entry.title.replace('/', '-').replace(':', '-')
            pdf_url = entry.link.replace("abs", "pdf") + ".pdf"
            filename = os.path.join(download_path, f"{title}.pdf")

            # Download the PDF file
            download_pdf(pdf_url, filename)

            markdown_content += f"- **[{title}]({pdf_url})**\n"

        return markdown_content

    except requests.exceptions.RequestException as e:
        return f"Error downloading papers: {e}"
    

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

    try:
        response = requests.get(ARXIV_API_URL, params=query_params)
        response.raise_for_status()  # Check if the request was successful
        feed = feedparser.parse(response.content)
        markdown_content = f"### Downloaded arXiv Papers (Keywords: `{', '.join(keywords)}`)\n\n"

        for entry in feed.entries:
            title = entry.title.replace('/', '-').replace(':', '-')
            pdf_url = entry.link.replace("abs", "pdf") + ".pdf"
            filename = os.path.join(download_path, f"{title}.pdf")

            # Download the PDF file
            download_pdf(pdf_url, filename)

            markdown_content += f"- **[{title}]({pdf_url})**\n"

        return markdown_content

    except requests.exceptions.RequestException as e:
        return f"Error downloading papers: {e}"
