import re
from datetime import datetime


class MT103Parser:
    """
    Best-effort MT103 text field extractor; does not validate authenticity.
    Extracts UETR, Sender Reference, Amount, Currency, Value Date,
    Sender & Beneficiary info, and Charge details.
    """

    @staticmethod
    def parse(raw_text: str) -> dict:
        result = {
            'uetr': '',
            'reference_number': '',
            'date_of_payment': None,
            'amount': None,
            'currency': '',
            'sender_name': '',
            'sender_account': '',
            'sender_bank_bic': '',
            'beneficiary_name': '',
            'beneficiary_account': '',
            'beneficiary_bank_bic': '',
            'charge_type': 'SHA',
            'raw_parsed_fields': {}
        }

        if not raw_text or not isinstance(raw_text, str):
            return result

        # 1. Extract UETR (Tag 121 or Block 3 {121:...})
        uetr_match = re.search(r'\{121:([a-fA-F0-9\-]{36})\}', raw_text)
        if not uetr_match:
            uetr_match = re.search(r':121:([a-fA-F0-9\-]{36})', raw_text)
        if not uetr_match:
            # Fallback UUID search
            uetr_match = re.search(r'\b([a-fA-F0-9]{8}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{12})\b', raw_text)
        if uetr_match:
            result['uetr'] = uetr_match.group(1).lower()

        # 2. Extract Field :20: (Transaction Reference Number)
        ref_match = re.search(r':20:([^\r\n]+)', raw_text)
        if not ref_match:
            ref_match = re.search(r'(?:F20:[^\n]*\n\s*/\s*|TRANSACTION\s+REFERENCE\s*:?\s*)([A-Za-z0-9\-_]+)', raw_text)
        if ref_match:
            result['reference_number'] = ref_match.group(1).strip()

        # 3. Extract Field :32A: (Value Date, Currency, Amount) or F32A / F33B
        field_32a_match = re.search(r':32A:(\d{6,8})([A-Z]{3})([0-9.,]+)', raw_text)
        if field_32a_match:
            date_str = field_32a_match.group(1)
            result['currency'] = field_32a_match.group(2).upper()
            amt_str = field_32a_match.group(3).replace(',', '.')
            try:
                result['amount'] = float(amt_str)
            except ValueError:
                pass

            try:
                if len(date_str) == 6:
                    dt = datetime.strptime(date_str, '%y%m%d').date()
                else:
                    dt = datetime.strptime(date_str, '%Y%m%d').date()
                result['date_of_payment'] = dt.strftime('%Y-%m-%d')
            except ValueError:
                pass
        else:
            # Fallback for printed bank advice layouts (like HSBC / F32A / F33B)
            curr_match = re.search(r'/\s*CURRENCY:\s*([A-Z]{3})', raw_text)
            if curr_match:
                result['currency'] = curr_match.group(1).upper()
            
            date_match = re.search(r'/\s*DATE:\s*(\d{4}-\d{2}-\d{2})', raw_text)
            if date_match:
                result['date_of_payment'] = date_match.group(1)

            amt_match = re.search(r'/\s*[€$£]?\s*([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]{2})?)', raw_text)
            if not amt_match:
                amt_match = re.search(r'AMOUNT:\s*[€$£]?\s*([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]{2})?)', raw_text)
            if amt_match:
                try:
                    clean_amt = amt_match.group(1).replace(',', '')
                    result['amount'] = float(clean_amt)
                except ValueError:
                    pass

        # 4. Extract Field :50K: (Ordering Customer / Sender)
        field_50_match = re.search(r':50[AK]:(?:/([^\r\n]+)\r?\n)?((?:[^\r\n:]+\r?\n?)+)', raw_text)
        if field_50_match:
            if field_50_match.group(1):
                result['sender_account'] = field_50_match.group(1).strip()
            lines = [l.strip() for l in field_50_match.group(2).strip().splitlines() if l.strip()]
            if lines:
                result['sender_name'] = " ".join(lines)
        else:
            # Advice layout F50K
            f50_advice = re.search(r'F50K:[^\n]*\n\s*/\s*([^\r\n]+)(?:\n\s*/\s*([0-9]+))?', raw_text)
            if f50_advice:
                result['sender_name'] = f50_advice.group(1).strip()
                if f50_advice.group(2):
                    result['sender_account'] = f50_advice.group(2).strip()

        # 5. Extract Field :59: (Beneficiary Customer)
        field_59_match = re.search(r':59[A]?:(?:/([^\r\n]+)\r?\n)?((?:[^\r\n:]+\r?\n?)+)', raw_text)
        if field_59_match:
            if field_59_match.group(1):
                result['beneficiary_account'] = field_59_match.group(1).strip()
            lines = [l.strip() for l in field_59_match.group(2).strip().splitlines() if l.strip()]
            if lines:
                result['beneficiary_name'] = " ".join(lines)
        else:
            # Advice layout F59A
            f59_advice = re.search(r'F59A:[^\n]*\n\s*/\s*([^\r\n]+)', raw_text)
            if f59_advice:
                result['beneficiary_name'] = f59_advice.group(1).strip()

        # 6. Extract Field :71A: (Details of Charges - OUR, SHA, BEN)
        field_71a_match = re.search(r':71A:([A-Z]{3})', raw_text)
        if field_71a_match:
            charge = field_71a_match.group(1).upper()
            if charge in ['OUR', 'SHA', 'BEN']:
                result['charge_type'] = charge

        # 7. Extract Sender Bank BIC from Block 1 or 2
        bic_match = re.search(r'\{1:F01([A-Z0-9]{8,12})', raw_text)
        if bic_match:
            result['sender_bank_bic'] = bic_match.group(1)[:8]

        # 8. Extract Beneficiary Bank BIC (:57A:)
        field_57a_match = re.search(r':57A:([A-Z0-9]{8,11})', raw_text)
        if field_57a_match:
            result['beneficiary_bank_bic'] = field_57a_match.group(1)

        return result
