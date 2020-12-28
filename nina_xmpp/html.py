from html.parser import HTMLParser


class LinebreakParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.convert_charrefs = True
        self.strict = False
        self._buf = []

    def handle_starttag(self, tag, attrs):
        if tag == 'br':
            self._buf.append('\n')

    def handle_data(self, data):
        self._buf.append(data)

    def close(self):
        super().close()
        return "".join(self._buf)


def strip_html(text):
    parser = LinebreakParser()
    parser.feed(text)
    return parser.close()
