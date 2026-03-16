import requests
#from rxn4chemistry import RXN4ChemistryWrapper
#from config import Config
from rdkit import Chem
import pandas as pd
import requests
#from langchain.chains import LLMChain
# from langchain_classic.chains import LLMChain
# from langchain import LLMchain

from langchain_core.prompts import PromptTemplate
#from langchain.llms import BaseLLM
from langchain_core.language_models.llms import BaseLLM


import tiktoken

# rxn4chem = RXN4ChemistryWrapper(
#         api_key=Config().RXN4CHEM_API_KEY,
#         base_url=Config().RXN4CHEM_BASE_URL,
#         project_id = Config().RXN4CHEM_PROJECT_ID
#     )

def is_smiles(text):
    try:
        m = Chem.MolFromSmiles(text, sanitize=False)
        if m is None:
            return False
        return True
    except:
        return False
    
def largest_mol(smiles):
    ss = smiles.split(".")
    ss.sort(key=lambda a: len(a))
    while not is_smiles(ss[-1]):
        rm = ss[-1]
        ss.remove(rm)
    return ss[-1]


    
safety_summary_prompt = (
    "Your task is to parse through the data provided and provide a summary of important health, laboratory, and environemntal safety information."
    "Focus on answering the following points, and follow the format \"Name: description\"."
    "Operator safety: Does this substance represent any danger to the person handling it? What are the risks? What precautions should be taken when handling this substance?"
    "GHS information: What are the GHS signal (hazard level: dangerous, warning, etc.) and GHS classification? What do these GHS classifications mean when dealing with this substance?"
    "Environmental risks: What are the environmental impacts of handling this substance."
    "Societal impact: What are the societal concerns of this substance? For instance, is it a known chemical weapon, is it illegal, or is it a controlled substance for any reason?"
    "For each point, use maximum two sentences. Use only the information provided in the paragraph below."
    "If there is not enough information in a category, you may fill in with your knowledge, but explicitly state so."
    "Here is the information:{data}"
)

summary_each_data = (
    "Please summarize the following, highlighting important information for health, laboratory and environemntal safety."
    "Do not exceed {approx_length} characters. The data is: {data}"
)

class MoleculeSafety:

    def __init__(self, llm: BaseLLM = None):
        self.clintox = pd.read_csv("https://deepchemdata.s3-us-west-1.amazonaws.com/datasets/clintox.csv.gz")
        self.pubchem_data = {}
        self.llm = llm

    def _fetch_pubchem_data(self, cas_number):
        """Fetch data from PubChem for a given CAS number, or use cached data if it's already been fetched."""
        if cas_number not in self.pubchem_data:
            try:
                url1 = (
                    f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/{cas_number}/cids/JSON"
                )
                url = f"https://pubchem.ncbi.nlm.nih.gov/rest/pug_view/data/compound/{requests.get(url1).json()['IdentifierList']['CID'][0]}/JSON"
                r = requests.get(url)
                # print(f"r is {r}")
                self.pubchem_data[cas_number] = r.json()
            except:
                return "Invalid molecule input, no Pubchem entry."
        return self.pubchem_data[cas_number]

    def ghs_classification(self, text):
        """Gives the ghs classification from Pubchem. Give this tool the name or CAS number of one molecule."""
        if is_smiles(text):
            return "Please input a valid CAS number."
        data = self._fetch_pubchem_data(text)
        if isinstance(data, str):
            return "Molecule not found in Pubchem."
        try:
            for section in data["Record"]["Section"]:
                if section.get("TOCHeading") == "Chemical Safety":
                    ghs = [
                        markup["Extra"]
                        for markup in section["Information"][0]["Value"][
                            "StringWithMarkup"
                        ][0]["Markup"]
                    ]
                    if ghs:
                        return ghs
        except (StopIteration, KeyError):
            return None


    @staticmethod
    def _scrape_pubchem(data, heading1, heading2, heading3):
        try:
            filtered_sections = []
            for section in data["Record"]["Section"]:
                toc_heading = section.get("TOCHeading")
                if toc_heading == heading1:
                    for section2 in section["Section"]:
                        if section2.get("TOCHeading") == heading2:
                            for section3 in section2["Section"]:
                                if section3.get("TOCHeading") == heading3:
                                    filtered_sections.append(section3)
            return filtered_sections
        except:
            return None

    def _get_safety_data(self, cas):
        data = self._fetch_pubchem_data(cas)
        safety_data = []

        iterations = [
            (["Health Hazards", "GHS Classification", "Hazards Summary", "NFPA Hazard Classification"], "Safety and Hazards", "Hazards Identification"),
            (["Explosive Limits and Potential", "Preventive Measures"], "Safety and Hazards", "Safety and Hazard Properties"),
            (["Inhalation Risk", "Effects of Long Term Exposure", "Personal Protective Equipment (PPE)"], "Safety and Hazards", "Exposure Control and Personal Protection"),
            (["Toxicity Summary", "Carcinogen Classification"], "Toxicity", "Toxicological Information")
        ]

        for items, header1, header2 in iterations:
            safety_data.extend([self._scrape_pubchem(data, header1, header2, item)] for item in items)

        return safety_data

    @staticmethod
    def _num_tokens(string, encoding_name="text-davinci-003"):
        """Returns the number of tokens in a text string."""
        encoding = tiktoken.encoding_for_model(encoding_name)
        num_tokens = len(encoding.encode(string))
        return num_tokens

    def get_safety_summary(self, cas):
        safety_data = self._get_safety_data(cas)
        approx_length = int((3500*4)/len(safety_data) - 0.1*((3500*4)/len(safety_data)))
        prompt_short = PromptTemplate(
            template=summary_each_data,
            input_variables=["data", "approx_length"]
        )
        llm_chain_short = LLMChain(prompt=prompt_short, llm=self.llm)

        llm_output = []
        for info in safety_data:
            if self._num_tokens(str(info)) > approx_length:
                trunc_info = str(info)[:approx_length]
                llm_output.append(llm_chain_short.run({"data":str(trunc_info), "approx_length":approx_length}))
            else:
                llm_output.append(llm_chain_short.run({"data":str(info), "approx_length":approx_length}))
        return llm_output
    
    import requests

def send_expasy_request(url, data):
    session = requests.Session()
    session.headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/116.0.0.0 Safari/537.36"
    }
    # Additional headers for the request
    headers = {
        "Accept": "*/*",
        "Accept-Encoding": "gzip, deflate, br",
        "Accept-Language": "en-US,en;q=0.9",
        "Origin": "https://web.expasy.org",
        "Content-Type": "application/x-www-form-urlencoded",
    }

    try:
        # Send POST request
        response = session.post(url, data=data, headers=headers, timeout=10)
        response.raise_for_status()  
        return response.text
    except requests.exceptions.RequestException as e:
        print("Network request error:", e)
        return None

def send_novopro_request(data):
    """
    Send a POST request to the Novopro server.

    Args:
        data (dict): The payload to send in the POST request.

    Returns:
        str: The server's response text.
    """
    session = requests.Session()
    session.headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/116.0.0.0 Safari/537.36"
    }
    headers = {
        "Accept": "*/*",
        "Accept-Encoding": "gzip, deflate, br",
        "Accept-Language": "zh-CN,zh;q=0.9,en-GB;q=0.8,en-US;q=0.7,en;q=0.6",
        "Origin": "https://www.novopro.cn",
    }

    url = "https://www.novopro.cn/plus/ppc.php"
    try:
        response = session.post(url, data=data, headers=headers)
        response.raise_for_status()
        return response.text
    except requests.exceptions.RequestException as e:
        print("Network request error:", e)
        return None

def send_chemspider_request(url, data):
    session = requests.Session()
    session.headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/116.0.0.0 Safari/537.36"
    }
    headers = {
        "Accept": "*/*",
        "Accept-Encoding": "gzip, deflate, br",
        "Accept-Language": "zh-CN,zh;q=0.9,en-GB;q=0.8,en-US;q=0.7,en;q=0.6",
        "Origin": "http://legacy.chemspider.com",
    }

    try:
        response = session.post(url=url, data=data, headers=headers)
        response.raise_for_status()
        return response.text
    except requests.exceptions.RequestException as e:
        print("网络请求错误:", e)
        return None