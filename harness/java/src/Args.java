/*
 * Args -- the long options this harness takes, read without a dependency.
 *
 * A jar pulled in only to parse "--run-id x" is a jar to pin, fingerprint and explain in the
 * record, for nothing. Only --name value is accepted; a bare flag or a missing value is refused
 * rather than guessed at, because a run started with a misread option is a run that has to be
 * thrown away.
 */
import java.util.HashMap;
import java.util.Map;

final class Args {

    private Args() {
    }

    static Map<String, String> parse(String[] argv) {
        Map<String, String> found = new HashMap<>();
        for (int i = 0; i < argv.length; i++) {
            String token = argv[i];
            if (!token.startsWith("--")) {
                throw new IllegalArgumentException("expected an option, found: " + token);
            }
            if (i + 1 >= argv.length) {
                throw new IllegalArgumentException("the option " + token + " has no value");
            }
            found.put(token.substring(2), argv[++i]);
        }
        return found;
    }

    static String need(Map<String, String> found, String name) {
        String value = found.get(name);
        if (value == null || value.isEmpty()) {
            throw new IllegalArgumentException("--" + name + " is required");
        }
        return value;
    }
}
