from allauth.account.adapter import DefaultAccountAdapter


class AccountAdapter(DefaultAccountAdapter):
    def get_client_ip(self, request):
        ip = (
            request.META.get("HTTP_X_REAL_IP")
            or request.META.get("HTTP_X_FORWARDED_FOR", "").split(",")[0].strip()
        )
        return ip or request.META.get("REMOTE_ADDR", "127.0.0.1")
