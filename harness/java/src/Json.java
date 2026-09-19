/*
 * Json -- just enough to write the message our Python client writes, and to read it back.
 *
 * The message has eight fields whose shapes we control, so a JSON library would be a dependency
 * to pin and fingerprint for no gain. What it must get right is escaping: an event id carrying a
 * quote or a backslash would otherwise produce a message the consumer cannot parse, and the run
 * would fail in a way that looks like the broker's fault.
 */
final class Json {

    private Json() {
    }

    /** Appends "name":"value" with the value escaped. */
    static StringBuilder field(StringBuilder out, String name, String value) {
        out.append('"').append(name).append("\":");
        escape(out, value);
        return out;
    }

    static StringBuilder escape(StringBuilder out, String value) {
        out.append('"');
        for (int i = 0; i < value.length(); i++) {
            char c = value.charAt(i);
            switch (c) {
                case '"':
                    out.append("\\\"");
                    break;
                case '\\':
                    out.append("\\\\");
                    break;
                case '\n':
                    out.append("\\n");
                    break;
                case '\r':
                    out.append("\\r");
                    break;
                case '\t':
                    out.append("\\t");
                    break;
                default:
                    if (c < 0x20) {
                        out.append(String.format("\\u%04x", (int) c));
                    } else {
                        out.append(c);
                    }
            }
        }
        return out.append('"');
    }

    /**
     * The value of a top-level string or number field, or null where the field is absent.
     *
     * The messages this reads are the ones LawProducer and kafka_producer.py write: flat, with no
     * nested objects and no arrays. It is deliberately not a general parser -- a general parser
     * that is wrong in a corner is worse here than one that only claims to read what we send.
     */
    static String value(String message, String name) {
        String key = "\"" + name + "\":";
        int at = message.indexOf(key);
        if (at < 0) {
            return null;
        }
        int from = at + key.length();
        if (from >= message.length()) {
            return null;
        }
        if (message.charAt(from) == '"') {
            StringBuilder out = new StringBuilder();
            for (int i = from + 1; i < message.length(); i++) {
                char c = message.charAt(i);
                if (c == '\\' && i + 1 < message.length()) {
                    char next = message.charAt(++i);
                    switch (next) {
                        case 'n': out.append('\n'); break;
                        case 'r': out.append('\r'); break;
                        case 't': out.append('\t'); break;
                        case 'u':
                            if (i + 4 < message.length()) {
                                out.append((char) Integer.parseInt(
                                        message.substring(i + 1, i + 5), 16));
                                i += 4;
                            }
                            break;
                        default: out.append(next);
                    }
                } else if (c == '"') {
                    return out.toString();
                } else {
                    out.append(c);
                }
            }
            return out.toString();
        }
        int end = from;
        while (end < message.length() && ",}".indexOf(message.charAt(end)) < 0) {
            end++;
        }
        return message.substring(from, end).trim();
    }
}
