import json
from selenium.webdriver.common.by import By
import time
import pandas as pd
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from tqdm import tqdm


#############################################################################################################
####################                           Scraping functions                        ####################
#############################################################################################################

def initialize_driver():
    """Initialize and return a Chrome WebDriver."""
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    driver = webdriver.Chrome(options=chrome_options)
    return driver

def navigate_to_search_page(driver):
    """Navigate to the search page and accept cookies."""
    search_url = "https://www.inrs.fr/publications/bdd/epicea/recherche.html"
    driver.get(search_url)
    
    time.sleep(1.5)
    cookie_button = driver.find_element(By.ID, "onetrust-accept-btn-handler")
    cookie_button.click()

def perform_search(driver):
    """Perform the search operation."""
    time.sleep(1.5)
    driver.switch_to.frame('siteExterneIframe')
    search_button = driver.find_element(By.XPATH, '//img[@src="/EPICEA/epicea.nsf/Rechercher.jpg"]')
    search_button.click()

def display_list(driver):
    """Click on the 'Display list' button."""
    time.sleep(1.5)
    display_button = driver.find_element(By.LINK_TEXT, "afficher la liste")
    display_button.click()

def get_total_pages(driver):
    """Get the total number of pages."""
    time.sleep(1.5)
    last_page_button = driver.find_element(By.LINK_TEXT, ">>")
    last_page_url = last_page_button.get_attribute('href')
    total_pages = int(last_page_url.split("'")[1])
    return total_pages

def extract_accident_ids(driver, total_pages):
    """Extract accident IDs from all pages."""
    accident_ids = []
    
    for page in tqdm(range(1, total_pages + 1)):
        ref_links = driver.find_elements(By.CLASS_NAME, 'lien')
        for link in ref_links:
            href = link.get_attribute('href')
            if "unid" in href:
                accident_ids.append(href)
        
        if page < total_pages:
            next_page_button = driver.find_element(By.LINK_TEXT, ">")
            next_page_button.click()
            time.sleep(1.5)
    
    return list(set(accident_ids))

def save_accident_ids(accident_ids):
    """Save accident IDs to a CSV file."""
    df = pd.DataFrame(accident_ids, columns=['Reference'])
    df.to_csv('Accident_IDs.csv', index=False)
    return len(accident_ids)

def load_data():
    """Load accident IDs and previously analyzed data."""
    df = pd.read_csv('Accident_IDs.csv')
    try:
        df_analyzed = pd.read_csv('Accident_database.csv', sep="|")
    except FileNotFoundError:
        df_analyzed = pd.DataFrame(columns=['Ref', 'Numero_dossier', 'Comite', 'Code_entreprise', 'Materiel', 'Resume', 'Adresse_pdf'])
    
    return df, df_analyzed

def filter_unanalyzed_data(df, df_analyzed):
    """Filter out already analyzed accident IDs."""
    analyzed_refs = df_analyzed['Ref']
    df = df[~df['Reference'].isin(analyzed_refs)]
    return df

def initialize_dataframe(df):
    """Initialize the dataframe with new columns."""
    new_columns = ['Numero_dossier', 'Comite', 'Code_entreprise', 'Materiel', 'Resume', 'Adresse_pdf']
    for col in new_columns:
        df[col] = None
    return df

def extract_accident_details(driver, ref):
    """Extract detailed information for a single accident."""
    driver.get(ref)
    
    details = {
        'Numero_dossier': get_content_after_text(driver, "Numéro du dossier : "),
        'Comite': get_content_after_text(driver, "Comité technique national : "),
        'Code_entreprise': get_content_after_text(driver, "Code entreprise : "),
        'Materiel': get_content_after_text(driver, "Matériel en cause : "),
        'Resume': get_accident_summary(driver, "Résumé de ").replace("\n", " ").replace("\r", " ")
    }
    
    pdf_links = []
    for link in driver.find_elements_by_class_name("lien"):
        onclick = link.get_attribute('onclick')
        if onclick and "Javascript: window.open('" in onclick:
            pdf_url = onclick.split("'")[1]
            if len(pdf_url) > 10:
                pdf_links.append(f"https://epicea.inrs.fr/{pdf_url.strip()}")
    
    details['Adresse_pdf'] = pdf_links
    return details

def process_accidents(df, waiting_time=1.5):
    """Process all unanalyzed accidents and update the database."""
    driver = initialize_driver()
    df_analyzed = pd.DataFrame(columns=['Ref', 'Numero_dossier', 'Comite', 'Code_entreprise', 'Materiel', 'Resume', 'Adresse_pdf'])
    
    try:
        for _, row in tqdm(df.iterrows(), total=df.shape[0]):
            ref = row['Reference']
            details = extract_accident_details(driver, ref)
            details['Ref'] = ref
            df_analyzed = df_analyzed.append(details, ignore_index=True)
            df_analyzed.to_csv('Accident_database.csv', sep='|', index=False, encoding="utf-8")
            time.sleep(waiting_time)
    finally:
        driver.quit()
    
    return df_analyzed

#############################################################################################################
####################                           LLM related functions                     ####################
#############################################################################################################

def standardize_metier(metier):
    """
    Standardise le champ 'metier' en le convertissant en chaîne de caractères.

    Args:
        metier (str ou list): Le métier à standardiser.

    Returns:
        str: Le métier standardisé.
    """
    if isinstance(metier, list):
        return ', '.join(metier)
    return str(metier)

def standardize_sex(sex):
    """
    Standardise le champ 'sexe' en le convertissant en 'Homme', 'Femme' ou None.

    Args:
        sex (str): Le sexe à standardiser.

    Returns:
        str ou None: Le sexe standardisé ou None si non reconnu.
    """
    sex = str(sex).lower().replace(",", "").replace("é", "e").replace("ou", "").replace("or", "").replace(" ", "")
    if sex in ['homme', 'masculin', 'male', 'm']:
        return 'Homme'
    elif sex in ['femme', 'feminin', 'female', 'f']:
        return 'Femme'
    return None

def standardize_zone(zone):
    """
    Standardise la zone du corps concernée par l'accident.

    Args:
        zone (str): La zone du corps à standardiser.

    Returns:
        str: La zone standardisée ou 'NA' si non reconnue.
    """
    zone_mapping = {
        'tete': ['crane', 'visage', 'cou', 'cerveau'],
        'torse': ['poitrine', 'torse', 'poumon'],
        'ventre': ['ventre', 'estomac'],
        'dos': ['dos', 'epaule'],
        'bras': ['bras', 'coude', 'epaule'],
        'main': ['main', 'doigt', 'poignet'],
        'jambe': ['genou', 'cuisse', 'mollet', 'tibia'],
        'pied': ['pied', 'cheville'],
        'posterieur': ['fesses'],
        'coeur': ['coeur']
    }

    zone = str(zone).lower()
    for standard_zone, keywords in zone_mapping.items():
        if zone in keywords or zone == standard_zone:
            return standard_zone
    return 'NA'

def parse_json_safely(json_string):
    """
    Parse une chaîne JSON de manière sécurisée, avec une tentative de nettoyage en cas d'échec.

    Args:
        json_string (str): La chaîne JSON à parser.

    Returns:
        dict ou None: Le dictionnaire parsé ou None en cas d'échec.
    """
    try:
        return json.loads(json_string)
    except json.JSONDecodeError as e:
        print(f"Erreur de parsing JSON : {e}")
        print(f"Contenu problématique : {json_string}")
        cleaned = json_string.strip()
        if cleaned.startswith("```json"):
            cleaned = cleaned[7:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError as e2:
            print(f"Échec du nettoyage : {e2}")
            return None

def validate_content(content_dict):
    """
    Valide le contenu du dictionnaire extrait.

    Args:
        content_dict (dict): Le dictionnaire à valider.

    Returns:
        bool: True si le contenu est valide, False sinon.
    """
    expected_keys = ['Metier', 'Sexe', 'Age', 'Type_accident', 'Blessure', 'Deces', 'Circulation', 'Malaise', 'Suicide', 'Machine', 'Cause']
    present_keys = [key for key in expected_keys if key in content_dict]
    missing_keys = [key for key in expected_keys if key not in content_dict]
    if missing_keys:
        print(f"Clés manquantes : {missing_keys}")
    return len(present_keys) >= 3

def add_default_values(content_dict):
    """
    Ajoute des valeurs par défaut pour les clés manquantes dans le dictionnaire.

    Args:
        content_dict (dict): Le dictionnaire à compléter.

    Returns:
        dict: Le dictionnaire avec les valeurs par défaut ajoutées.
    """
    default_values = {
        'Metier': None, 'Sexe': None, 'Age': None, 'Type_accident': None,
        'Blessure': None, 'Deces': None, 'Circulation': None, 'Malaise': None,
        'Suicide': None, 'Machine': None, 'Cause': None
    }
    for key, value in default_values.items():
        if key not in content_dict:
            content_dict[key] = value
    return content_dict

def clean_and_standardize_content(content_dict):
    """
    Nettoie et standardise le contenu du dictionnaire.

    Args:
        content_dict (dict): Le dictionnaire à nettoyer et standardiser.

    Returns:
        dict: Le dictionnaire nettoyé et standardisé.
    """
    for key, value in content_dict.items():
        if key == 'Sexe':
            content_dict[key] = standardize_sex(value)
        elif key == 'Metier':
            content_dict[key] = standardize_metier(value)
        elif key == 'Zone':
            content_dict[key] = standardize_zone(value)
        elif isinstance(value, list):
            content_dict[key] = ', '.join(map(str, value))
        elif value is None:
            content_dict[key] = 'Non spécifié'
        elif isinstance(value, bool):
            content_dict[key] = 'Oui' if value else 'Non'
        else:
            content_dict[key] = str(value)
    return content_dict

def process_content_dict(content_dict):
    """
    Traite le dictionnaire de contenu, qu'il soit déjà un dictionnaire ou une chaîne JSON.

    Args:
        content_dict (dict ou str): Le contenu à traiter.

    Returns:
        dict: Le dictionnaire traité.

    Raises:
        TypeError: Si le type de content_dict n'est ni un dict ni une str.
    """
    if isinstance(content_dict, dict):
        return content_dict
    elif isinstance(content_dict, str):
        return json.loads(content_dict)
    else:
        raise TypeError(f"Type inattendu pour content_dict: {type(content_dict)}")

def get_content_after_text(driver, text):
    """
    Extrait le contenu après un texte spécifique dans une page web.

    Args:
        driver (WebDriver): L'instance du driver Selenium.
        text (str): Le texte après lequel extraire le contenu.

    Returns:
        str: Le contenu extrait.
    """
    text_for_xpath = text.replace(' ', '&#160;')
    nbsp = '\xa0'
    xpath_text_part = text_for_xpath.replace('&#160;', nbsp)
    xpath = f"//td[contains(., '{xpath_text_part}')]/following-sibling::td[1]"
    content_td = driver.find_element(By.XPATH, xpath)
    return content_td.text.strip()

def get_accident_summary(driver, text):
    """
    Extrait le résumé d'un accident à partir d'une page web.

    Args:
        driver (WebDriver): L'instance du driver Selenium.
        text (str): Le texte utilisé pour localiser le résumé.

    Returns:
        str: Le résumé de l'accident.
    """
    nbsp = '\xa0'
    text_for_xpath = text.replace(' ', nbsp)
    xpath = f"//td[contains(., '{text_for_xpath}')]/following-sibling::td[1]//div"
    summary_div = driver.find_element(By.XPATH, xpath)
    return summary_div.text.strip()

