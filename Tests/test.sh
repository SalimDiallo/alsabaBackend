curl --request POST \
     --url https://verification.didit.me/v2/phone/check/ \
     --header 'accept: application/json' \
     --header 'content-type: application/json' \
     --header 'x-api-key: ovsPKRfqclIRl9nwTNUy19yJeScxYDbnh0JS9rjBTuU' \
     --data '
{
  "phone_number": "+212660620565",
  "code": "980383",
  "duplicated_phone_number_action": "NO_ACTION",
  "disposable_number_action": "NO_ACTION",
  "voip_number_action": "NO_ACTION"
}
'