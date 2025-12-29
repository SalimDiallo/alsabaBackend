curl -X POST "https://verification.didit.me/v2/phone/send" \
  -H "accept: application/json" \
  -H "x-api-key: ovsPKRfqclIRl9nwTNUy19yJeScxYDbnh0JS9rjBTuU" \
  -H "Content-Type: application/json" \
  -d '{
    "phone_number": "+2120660620565",
    "options": {
      "code_size": 6
    },
    "signals": {
      "ip": "192.168.1.100",
      "user_agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 14_0 like Mac OS X)"
    }
  }'


  {
    "success": true,
    "action": "register",
    "message": "Code de vérification envoyé avec succès",
    "session_key": "auth_15af36f4e7ba41bd",
    "request_id": "ea5fae7f-a987-43f9-80fe-957389464204",
    "phone_number": "+212660620565",
    "user_exists": false,
    "expires_in": 300,
    "metadata": {
        "code_size": 6,
        "channel": "sms",
        "max_attempts": 3
    }
}
{ "phone_number": "+212660620565",
    "code": "830923",
    "session_key": "auth_60ac50e2bc5a410e"
  }

  {
    "phone_number": "+2120660620565"
  }

  {
    "phone_number": "+2120684499227"
  }

  {
    "success": true,
    "action": "register",
    "message": "Code de vérification envoyé avec succès",
    "session_key": "auth_a63651b05fff40d1",
    "request_id": "ff9a73dc-bac9-4672-935e-0f081b493970",
    "phone_number": "+212660620565",
    "user_exists": false,
    "expires_in": 300,
    "metadata": {
        "code_size": 6,
        "channel": "sms",
        "max_attempts": 3
    }