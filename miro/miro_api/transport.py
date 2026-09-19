"""HTTP-транспорт с повторными попытками для Miro API."""

import http.client
import json
import time
import urllib.error
import urllib.parse
import urllib.request


class MiroApiError(RuntimeError):
    """Ошибка запроса к Miro API."""


class MiroTransport:
    """Выполняет HTTP-запросы и не содержит логики размещения."""

    def __init__(self, token: str, api_url: str = "https://api.miro.com", sleep=time.sleep):
        self.token = token
        self.api_url = api_url.rstrip("/")
        self.sleep = sleep

    def request(self, method, path, body=None, raw=None, content_type="application/json",
                soft=False, timeout=90, tries=5):
        """Выполнить запрос с retry для временных ошибок."""
        for attempt in range(1, tries + 1):
            data = raw if raw is not None else (
                json.dumps(body).encode("utf-8") if body is not None else None
            )
            request = urllib.request.Request(
                self.api_url + "/v2" + path,
                data=data,
                method=method,
                headers={
                    "Authorization": "Bearer " + self.token,
                    "Content-Type": content_type,
                },
            )
            try:
                with urllib.request.urlopen(request, timeout=timeout) as response:
                    return response.status, response.read()
            except urllib.error.HTTPError as exc:
                text = exc.read().decode("utf-8", "replace")
                if exc.code == 429 and attempt < tries:
                    self.sleep(float(exc.headers.get("Retry-After") or 2 * attempt))
                    continue
                if exc.code >= 500 and attempt < tries:
                    self.sleep(2 * attempt)
                    continue
                if exc.code == 403:
                    raise MiroApiError(
                        "Miro HTTP 403: у приложения нет доступа к этой доске. "
                        "Открой доску в Miro и предоставь приложению доступ к данным доски.\n%s"
                        % text[:400]
                    )
                if soft:
                    return exc.code, text.encode("utf-8")
                raise MiroApiError("Miro HTTP %d: %s" % (exc.code, text[:400]))
            except (urllib.error.URLError, TimeoutError, http.client.HTTPException, OSError) as exc:
                if attempt == tries:
                    raise MiroApiError("нет связи с Miro после %d попыток: %s" % (tries, exc))
                self.sleep(3 * attempt)
        raise MiroApiError("Miro слишком часто отказывает")

    def upload(self, path, file_path, metadata, timeout=180):
        """Загрузить файл изображения multipart-запросом."""
        boundary = "----productboard%d" % int(time.time() * 1000)
        parts = [
            ("--%s\r\nContent-Disposition: form-data; name=\"data\"\r\n"
             "Content-Type: application/json\r\n\r\n%s\r\n" %
             (boundary, json.dumps(metadata))).encode("utf-8")
        ]
        with open(file_path, "rb") as stream:
            blob = stream.read()
        parts.append(("--%s\r\nContent-Disposition: form-data; name=\"resource\"; "
                      "filename=\"%s\"\r\nContent-Type: image/jpeg\r\n\r\n" %
                      (boundary, file_path.rsplit("/", 1)[-1])).encode("utf-8"))
        parts.append(blob + b"\r\n")
        parts.append(("--%s--\r\n" % boundary).encode("utf-8"))
        return self.request(
            "POST",
            path,
            raw=b"".join(parts),
            content_type="multipart/form-data; boundary=%s" % boundary,
            soft=True,
            timeout=timeout,
        )
