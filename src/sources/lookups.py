"""Small code -> name tables and label helpers."""
COUNTRIES = {code: name for code, name in (item.strip().split(" ", 1) for item in """AF Afghanistan|AL Albania|DZ Algeria|AD Andorra|AO Angola|AG Antigua and Barbuda|AR Argentina|AM Armenia|AU Australia|AT Austria|AZ Azerbaijan|BS Bahamas|BH Bahrain|BD Bangladesh|BB Barbados|BY Belarus|BE Belgium|BZ Belize|BJ Benin|BT Bhutan|BO Bolivia|BA Bosnia and Herzegovina|BW Botswana|BR Brazil|BN Brunei|BG Bulgaria|BF Burkina Faso|BI Burundi|KH Cambodia|CM Cameroon|CA Canada|CV Cape Verde|CF Central African Republic|TD Chad|CL Chile|CN China|CO Colombia|KM Comoros|CG Congo|CD DR Congo|CR Costa Rica|CI Ivory Coast|HR Croatia|CU Cuba|CY Cyprus|CZ Czechia|DK Denmark|DJ Djibouti|DM Dominica|DO Dominican Republic|EC Ecuador|EG Egypt|SV El Salvador|GQ Equatorial Guinea|ER Eritrea|EE Estonia|SZ Eswatini|ET Ethiopia|FJ Fiji|FI Finland|FR France|GA Gabon|GM Gambia|GE Georgia|DE Germany|GH Ghana|GR Greece|GD Grenada|GT Guatemala|GN Guinea|GW Guinea-Bissau|GY Guyana|HT Haiti|HN Honduras|HK Hong Kong|HU Hungary|IS Iceland|IN India|ID Indonesia|IR Iran|IQ Iraq|IE Ireland|IL Israel|IT Italy|JM Jamaica|JP Japan|JO Jordan|KZ Kazakhstan|KE Kenya|KI Kiribati|KP North Korea|KR South Korea|XK Kosovo|KW Kuwait|KG Kyrgyzstan|LA Laos|LV Latvia|LB Lebanon|LS Lesotho|LR Liberia|LY Libya|LI Liechtenstein|LT Lithuania|LU Luxembourg|MO Macao|MG Madagascar|MW Malawi|MY Malaysia|MV Maldives|ML Mali|MT Malta|MH Marshall Islands|MR Mauritania|MU Mauritius|MX Mexico|FM Micronesia|MD Moldova|MC Monaco|MN Mongolia|ME Montenegro|MA Morocco|MZ Mozambique|MM Myanmar|NA Namibia|NR Nauru|NP Nepal|NL Netherlands|NZ New Zealand|NI Nicaragua|NE Niger|NG Nigeria|MK North Macedonia|NO Norway|OM Oman|PK Pakistan|PW Palau|PS Palestine|PA Panama|PG Papua New Guinea|PY Paraguay|PE Peru|PH Philippines|PL Poland|PT Portugal|PR Puerto Rico|QA Qatar|RO Romania|RU Russia|RW Rwanda|KN Saint Kitts and Nevis|LC Saint Lucia|VC Saint Vincent and the Grenadines|WS Samoa|SM San Marino|ST Sao Tome and Principe|SA Saudi Arabia|SN Senegal|RS Serbia|SC Seychelles|SL Sierra Leone|SG Singapore|SK Slovakia|SI Slovenia|SB Solomon Islands|SO Somalia|ZA South Africa|SS South Sudan|ES Spain|LK Sri Lanka|SD Sudan|SR Suriname|SE Sweden|CH Switzerland|SY Syria|TW Taiwan|TJ Tajikistan|TZ Tanzania|TH Thailand|TL Timor-Leste|TG Togo|TO Tonga|TT Trinidad and Tobago|TN Tunisia|TR Turkey|TM Turkmenistan|TV Tuvalu|UG Uganda|UA Ukraine|AE United Arab Emirates|GB United Kingdom|US United States|UY Uruguay|UZ Uzbekistan|VU Vanuatu|VA Vatican City|VE Venezuela|VN Vietnam|YE Yemen|ZM Zambia|ZW Zimbabwe|FO Faroe Islands|GL Greenland|GI Gibraltar|GU Guam|IM Isle of Man|JE Jersey|GG Guernsey|AW Aruba|BM Bermuda|KY Cayman Islands|NC New Caledonia|PF French Polynesia|YU Yugoslavia|SU Soviet Union|CS Czechoslovakia|DD East Germany|XE Europe|XW Worldwide|XG East Germany|XU Soviet Union|AN Netherlands Antilles""".split("|"))}
COUNTRIES["UK"] = "United Kingdom"
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
    """'RS' -> 'Serbia'. Something that is already a name is left as it is."""
    c = str(code).strip()
    return COUNTRIES.get(c.upper(), c) if len(c) <= 3 else c


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
