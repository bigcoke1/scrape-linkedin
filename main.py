from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.wait import WebDriverWait
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
import google.generativeai as genai
from bs4 import BeautifulSoup
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed

import sqlite3
import time
import ast
from datetime import datetime, timedelta
import os

BASE_URL = "https://www.linkedin.com/jobs/view/"
START_ID = 9980000

ACCOUNT_INFO = {"email": "a23539945@gmail.com", "password": "JGJ%.KfP!ybwjg4"}

model = genai.GenerativeModel("gemini-1.5-flash")

def init_webdriver():
    chrome_options = Options()
    chrome_options.add_argument("--headless=new")
    prefs = {
        "download.default_directory": "/dev/null",
        "download.prompt_for_download": False,
        "download.directory_upgrade": True,
        "safebrowsing.enabled": True
    }
    chrome_options.add_experimental_option("prefs", prefs)
    
    driver = webdriver.Chrome(options=chrome_options)

    return driver

"""def sign_in():
    driver.get("https://www.linkedin.com/")

    WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
    button_selector = "#main-content > section.section.min-h-\[560px\].flex-nowrap.pt-\[40px\].babybear\:flex-col.babybear\:min-h-\[0\].babybear\:px-mobile-container-padding.babybear\:pt-\[24px\] > div > div > a"
    sign_in_button = driver.find_element(By.CSS_SELECTOR, button_selector)
    sign_in_button.click()
    
    email_input = driver.find_element(By.CSS_SELECTOR, "#username")
    password_input = driver.find_element(By.CSS_SELECTOR, "#password")

    email_input.send_keys(ACCOUNT_INFO["email"])
    password_input.send_keys(ACCOUNT_INFO["password"])
    password_input.send_keys(Keys.ENTER)
    
    print(f"signed in to {ACCOUNT_INFO["email"]}")
"""

def get_link(id):
    return BASE_URL + str(id)

def get_starting_id():
    con = sqlite3.connect("jobs.db")
    cur = con.cursor()

    #get the latest id scanned. If no latest, id = START_ID
    id = cur.execute("SELECT id FROM job_links ORDER BY id DESC LIMIT 1")
    id = id.fetchone()[0] or START_ID

    return id

def scrape_text(link):
    print("scraping text...")
    driver = init_webdriver()

    driver.get(link)

    time.sleep(0.75)
    WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
    html = driver.page_source
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text()

    driver.quit()

    return text

def ask_gemini(job_title, text):
    current_date = datetime.now().date()
    print("asking gemini...")
    prompt = ( 
        f"""Give a response in Python Dict format
            '{job_title}': True/False whether the description matches or similar to this job title,
            'actual_job_title': the actual job title based on the description
            'organization': the organization hiring this position
            'post_date': date in (mm-dd-yy) format (note today's date is {current_date}),
            'summary': summary of job description
        """)
    response = model.generate_content([text, prompt])

    response = response.text
    if type(response) == str:
        start = response.index("{")
        end = response.index("}") + 1
        response = response[start:end]
    return ast.literal_eval(response)

def is_outdated(date):
    format_string = "%m-%d-%y"
    date = datetime.strptime(date, format_string).date()
    current_date = datetime.now().date()

    return abs(date - current_date) > timedelta(days=30)

def get_path(id, date):
    path = f"{id}-{date}.txt"
    path = os.path.join("result", path)
    return path

def eval_response(response, job_title, id, link, replace=False):
    date = response["post_date"]
    if bool(response[job_title]) and not is_outdated(date) and response["organization"] != "LinkedIn":
        with open(get_path(id, date), "w") as f:
            f.write(str(response))

    con = sqlite3.connect("jobs.db")
    cur = con.cursor()
    cur.execute("SELECT * FROM job_links WHERE id = ?", [id])
    entry = cur.fetchone()
    if entry and replace:
        cur.execute("DELETE FROM job_links WHERE id = ?", [id])
    if not entry or replace:
        cur.execute("INSERT INTO job_links (id, desired_result, organization, link, job_title, date) VALUES (?, ?, ?, ?, ?, ?)",
                    [id, response[job_title], response["organization"], link, response["actual_job_title"], date])
    con.commit()
    con.close()

def collect_result(i):
    link = get_link(i)
    print("now looking at " + link)
    try:
        response = requests.get(link)
        status_code = response.status_code
        if status_code == 404:
            response.raise_for_status()
        else:
            text = scrape_text(link)
            response = ask_gemini(job_title, text)
            response["link"] = link
            print(response)
            eval_response(response, job_title, i, link)
    except Exception as e:
        print(link + e)
        if status_code == 404:
            pass
        else: 
            collect_result(i)

def iter_result(id_list):
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {executor.submit(collect_result, i): i for i in id_list}
        for future in as_completed(futures):
            try:
                print(f"{future} job done")
            except Exception as exc:
                print(f"An error occurred: {exc}")

def clean_data():
    con = sqlite3.connect("jobs.db")
    cur = con.cursor()

    bad_entries = cur.execute("""SELECT id FROM job_links WHERE job_title IS NULL OR job_title = 'Not Found' 
                            OR job_title = 'Not found' OR job_title = 'Not available' OR job_title = 'None' 
                            OR organization IS NULL OR organization = 'LinkedIn' OR job_title = 'N/A'""")
    bad_entries = bad_entries.fetchall()
    bad_entries = [bad_entry[0] for bad_entry in bad_entries]
    count = len(bad_entries)
    if count:
        iter_result(bad_entries) #iterate through the links of bad entries again
        
        #if there are still bad entries, delete them
        bad_entries = cur.execute("""SELECT id FROM job_links WHERE job_title IS NULL OR job_title = 'Not Found' 
                                  OR job_title = 'Not found' OR job_title = 'Not available' OR job_title = 'None' 
                                  OR organization IS NULL OR organization = 'LinkedIn' OR job_title = 'N/A'""") 
        bad_entries = bad_entries.fetchall()
        for bad_entry in bad_entries:
            cur.execute("DELETE FROM job_links WHERE id = ?", [bad_entry[0]])
        con.commit()
    con.close()

    return count

if __name__ == "__main__":
    job_title = input("Job title you want to search for: \n>>> ")
    job_title = job_title.lower()
    iterations = int(input("how many iterations? \n>>> "))
    if iterations:
        id = get_starting_id() + 1
        iter_result(range(id, id + iterations))

    print("all current jobs done... cleaning previous data...")
    count = clean_data() #clean entries after each time we run
    print(f"done cleaning, {count} entries deleted or replaced")