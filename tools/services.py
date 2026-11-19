import re
from difflib import SequenceMatcher


class IBANValidatorService:
    """
    ISO 13616 compliant IBAN validator using official Modulo-97 checksum logic.
    """
    
    # Official country IBAN lengths
    IBAN_LENGTHS = {
        'AL': 28, 'AD': 24, 'AT': 20, 'AZ': 28, 'BH': 22, 'BE': 16, 'BA': 20,
        'BR': 29, 'BG': 22, 'CR': 22, 'HR': 21, 'CY': 28, 'CZ': 24, 'DK': 18,
        'DO': 28, 'EE': 20, 'FO': 18, 'FI': 18, 'FR': 27, 'GE': 22, 'DE': 22,
        'GI': 23, 'GR': 27, 'GL': 18, 'GT': 28, 'HU': 28, 'IS': 26, 'IE': 22,
        'IL': 23, 'IT': 27, 'JO': 30, 'KZ': 20, 'KW': 30, 'LV': 21, 'LB': 28,
        'LI': 21, 'LT': 20, 'LU': 20, 'MK': 19, 'MT': 31, 'MR': 27, 'MU': 30,
        'MC': 27, 'MD': 24, 'ME': 22, 'NL': 18, 'NO': 15, 'PK': 24, 'PS': 29,
        'PL': 28, 'PT': 25, 'QA': 29, 'RO': 24, 'SM': 27, 'SA': 24, 'RS': 22,
        'SK': 24, 'SI': 19, 'ES': 24, 'SE': 24, 'CH': 21, 'TN': 24, 'TR': 26,
        'AE': 23, 'GB': 22, 'VG': 24, 'QA': 29
    }

    COUNTRY_NAMES = {
        'AE': 'United Arab Emirates', 'GB': 'United Kingdom', 'DE': 'Germany',
        'FR': 'France', 'CH': 'Switzerland', 'US': 'United States', 'SA': 'Saudi Arabia',
        'QA': 'Qatar', 'TR': 'Turkey', 'ES': 'Spain', 'IT': 'Italy', 'NL': 'Netherlands',
        'BE': 'Belgium', 'SE': 'Sweden', 'NO': 'Norway', 'SG': 'Singapore'
    }

    @classmethod
    def validate(cls, raw_iban: str) -> dict:
        clean_iban = re.sub(r'[\s\-]+', '', (raw_iban or '').upper())
        
        result = {
            'iban': clean_iban,
            'is_valid': False,
            'country_code': '',
            'country_name': '',
            'expected_length': 0,
            'actual_length': len(clean_iban),
            'bank_code': '',
            'account_number': '',
            'checksum': '',
            'error_message': ''
        }

        if len(clean_iban) < 4:
            result['error_message'] = 'IBAN is too short.'
            return result

        country = clean_iban[:2]
        result['country_code'] = country
        result['country_name'] = cls.COUNTRY_NAMES.get(country, f"Country ({country})")
        result['checksum'] = clean_iban[2:4]

        # Check country existence and length
        expected_len = cls.IBAN_LENGTHS.get(country)
        result['expected_length'] = expected_len or 0

        if expected_len and len(clean_iban) != expected_len:
            result['error_message'] = f"Invalid length for {country}. Expected {expected_len} characters, got {len(clean_iban)}."
            return result

        # Check format: first 2 letters, then 2 digits, then alphanumeric
        if not re.match(r'^[A-Z]{2}[0-9]{2}[A-Z0-9]+$', clean_iban):
            result['error_message'] = 'Invalid format. Must start with 2 country letters, 2 check digits, followed by alphanumeric characters.'
            return result

        # Modulo-97 algorithm:
        # Move first 4 characters to the end
        rearranged = clean_iban[4:] + clean_iban[:4]

        # Replace each letter with two digits (A=10, B=11, ... Z=35)
        numeric_str = ''
        for char in rearranged:
            if char.isalpha():
                numeric_str += str(ord(char) - 55)
            else:
                numeric_str += char

        # Compute mod 97
        try:
            mod97 = int(numeric_str) % 97
            if mod97 == 1:
                result['is_valid'] = True
                result['bank_code'] = clean_iban[4:8]
                result['account_number'] = clean_iban[8:]
            else:
                result['error_message'] = f"Checksum failure (Modulo-97 validation remainder is {mod97}, expected 1)."
        except ValueError:
            result['error_message'] = 'Character conversion error.'

        return result


class SanctionsScreenerService:
    """
    Name-matching demonstration against a small fictional sample list.
    This is not sanctions screening and must not issue compliance decisions.
    """

    # Fictional records used only to demonstrate matching behavior.
    WATCHLIST_DATABASE = [
        {
            'name': 'SAMPLE ENTITY ALPHA',
            'type': 'Entity',
            'list': 'Fictional sample list',
            'program': 'Demo only',
            'country': 'Not applicable',
            'remarks': 'Fictional record for testing the name matcher.'
        },
        {
            'name': 'SAMPLE BANK BETA',
            'type': 'Bank',
            'list': 'Fictional sample list',
            'program': 'Demo only',
            'country': 'Not applicable',
            'remarks': 'Fictional record for testing the name matcher.'
        },
        {
            'name': 'SAMPLE VESSEL GAMMA',
            'type': 'Vessel',
            'list': 'Fictional sample list',
            'program': 'Demo only',
            'country': 'Not applicable',
            'remarks': 'Fictional record for testing the name matcher.'
        }
    ]

    @classmethod
    def screen(cls, query_name: str, threshold: float = 0.65) -> dict:
        query_clean = (query_name or '').strip().upper()
        
        matches = []
        if not query_clean:
            return {'query': query_clean, 'total_matches': 0, 'risk_level': 'NO SAMPLE MATCH', 'data_scope': 'fictional_sample', 'matches': []}

        for record in cls.WATCHLIST_DATABASE:
            target_name = record['name'].upper()
            
            # 1. Exact or Substring match
            if query_clean in target_name or target_name in query_clean:
                score = 0.95 if query_clean == target_name else 0.85
            else:
                # 2. Sequence similarity
                score = SequenceMatcher(None, query_clean, target_name).ratio()

            if score >= threshold:
                matches.append({
                    **record,
                    'similarity_score': round(score * 100, 1)
                })

        # Sort matches by highest similarity
        matches.sort(key=lambda x: x['similarity_score'], reverse=True)

        risk_level = 'SAMPLE MATCH' if matches else 'NO SAMPLE MATCH'

        return {
            'query': query_name,
            'total_matches': len(matches),
            'risk_level': risk_level,
            'data_scope': 'fictional_sample',
            'matches': matches
        }
