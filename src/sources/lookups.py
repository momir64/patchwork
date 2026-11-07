"""Small code -> name tables and label helpers."""
COUNTRIES = {"US": "United States", "GB": "United Kingdom", "UK": "United Kingdom", "CA": "Canada", "AU": "Australia",
             "DE": "Germany", "FR": "France", "IT": "Italy", "ES": "Spain", "JP": "Japan", "KR": "South Korea",
             "CN": "China", "IN": "India", "SE": "Sweden", "NO": "Norway", "DK": "Denmark", "FI": "Finland",
             "NL": "Netherlands", "BE": "Belgium", "IE": "Ireland", "NZ": "New Zealand", "RS": "Serbia",
             "RU": "Russia", "PL": "Poland", "BR": "Brazil", "MX": "Mexico", "AR": "Argentina", "TR": "Turkey",
             "IL": "Israel", "HK": "Hong Kong", "TW": "Taiwan", "TH": "Thailand", "AT": "Austria",
             "CH": "Switzerland", "CZ": "Czechia", "HU": "Hungary", "IS": "Iceland", "ZA": "South Africa",
             "UA": "Ukraine", "HR": "Croatia", "GR": "Greece"}
LANGUAGES = {"en": "English", "ja": "Japanese", "ko": "Korean", "fr": "French", "de": "German", "es": "Spanish",
             "it": "Italian", "sv": "Swedish", "no": "Norwegian", "da": "Danish", "fi": "Finnish", "nl": "Dutch",
             "ru": "Russian", "sr": "Serbian", "pl": "Polish", "pt": "Portuguese", "zh": "Chinese", "cn": "Cantonese",
             "hi": "Hindi", "tr": "Turkish", "he": "Hebrew", "th": "Thai", "hr": "Croatian", "cs": "Czech"}


COUNTRY_LANGUAGE = {
    "US": "English", "GB": "English", "UK": "English", "AU": "English", "CA": "English", "IE": "English", "NZ": "English",
    "ZA": "English", "DE": "German", "AT": "German", "CH": "German", "FR": "French", "IT": "Italian", "ES": "Spanish",
    "MX": "Spanish", "AR": "Spanish", "JP": "Japanese", "KR": "Korean", "CN": "Chinese", "TW": "Chinese", "HK": "Cantonese",
    "SE": "Swedish", "NO": "Norwegian", "DK": "Danish", "FI": "Finnish", "NL": "Dutch", "BE": "Dutch", "RU": "Russian",
    "PL": "Polish", "BR": "Portuguese", "PT": "Portuguese", "TR": "Turkish", "IL": "Hebrew", "IS": "Icelandic",
    "CZ": "Czech", "HU": "Hungarian", "UA": "Ukrainian", "GR": "Greek", "IN": "Hindi", "TH": "Thai",
    "RS": "Serbo-Croatian", "HR": "Serbo-Croatian", "BA": "Serbo-Croatian", "ME": "Serbo-Croatian",
}


def country_language(code):
    """Main language of a country - used as an approximation for an artist's language."""
    return COUNTRY_LANGUAGE.get(str(code).upper())


def country(code) -> str:
    return COUNTRIES.get(str(code).upper(), str(code).upper())


def language(code) -> str:
    return LANGUAGES.get(str(code).lower(), str(code))


def title_case(tag: str) -> str:
    return "-".join(w.capitalize() for w in tag.strip().split("-")) if "-" in tag else tag.strip().title()


def movie_label(title: str, year) -> str:
    return f"{title} ({year})" if year else title


def split_movie_label(label: str):
    """'Dune (2021)' -> ('Dune', '2021'); anything else -> (label, None)."""
    if label.endswith(")") and label[-6:-5] == "(" and label[-5:-1].isdigit():
        return label[:-7].strip(), label[-5:-1]
    return label, None
