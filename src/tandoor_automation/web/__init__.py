"""Die Oberfläche im Browser, vom Server gerendert.

FastAPI nimmt die Anfragen an, Jinja2 baut daraus HTML, und htmx tauscht nach einem Klick nur
den Teil der Seite, der sich geändert hat. Eigenes JavaScript gibt es damit fast keins, und
einen Build-Schritt fürs Frontend gar nicht: htmx und Pico CSS liegen fertig unter `static/`.

Die Seiten rufen dieselben Funktionen aus `workflow` und `store` auf wie die CLI, nur die Ein-
und Ausgabe unterscheidet sich. Ein Login gibt es nicht, abgesichert ist der Dienst über den
Netzweg: erreichbar nur im Heimnetz und über WireGuard.
"""
