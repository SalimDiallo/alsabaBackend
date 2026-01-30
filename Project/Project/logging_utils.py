def redact_sensitive_data(logger, log_method, event_dict):
    """
    Redact critical PII/PCI-DSS data from structured logs.
    """
    SENSITIVE_KEYS = {
        'password', 'token', 'access_token', 'refresh_token', 
        'card_number', 'cvv', 'card_cvv', 'cvc', 
        'pin', 'otp', 'secret', 'key'
    }
    
    # Recursively redact dictionary
    def redact(data):
        if isinstance(data, dict):
            new_data = {}
            for k, v in data.items():
                if k.lower() in SENSITIVE_KEYS:
                    new_data[k] = "***REDACTED***"
                else:
                    new_data[k] = redact(v)
            return new_data
        elif isinstance(data, list):
            return [redact(item) for item in data]
        return data

    return redact(event_dict)
