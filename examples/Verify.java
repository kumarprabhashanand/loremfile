// Fetch one fixture and check it against the published hash. Run: java Verify.java
// Hashes come from sha256sums.txt rather than manifest.json: one line per file, so no
// JSON library is needed. Both are published and carry the same hashes.
import java.net.URI;
import java.net.http.*;
import java.security.MessageDigest;
import java.util.HexFormat;

public class Verify {
    static final String BASE = "https://loremfile.dev/", WANTED = "pdf/minimal.pdf";

    public static void main(String[] args) throws Exception {
        HttpClient client = HttpClient.newHttpClient();
        String sums = get(client, "sha256sums.txt", HttpResponse.BodyHandlers.ofString());
        String want = sums.lines()
                .filter(line -> line.endsWith("  " + WANTED))
                .findFirst().orElseThrow()
                .split(" ")[0];

        byte[] body = get(client, WANTED, HttpResponse.BodyHandlers.ofByteArray());
        String got = HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(body));
        if (!got.equals(want)) throw new IllegalStateException(WANTED + ": " + got + " != " + want);
        System.out.println(WANTED + ": " + body.length + " bytes, sha256 matches");
    }

    static <T> T get(HttpClient client, String path, HttpResponse.BodyHandler<T> as)
            throws Exception {
        var request = HttpRequest.newBuilder(URI.create(BASE + path)).build();
        HttpResponse<T> response = client.send(request, as);
        if (response.statusCode() != 200) throw new IllegalStateException(path + " answered " + response.statusCode());
        return response.body();
    }
}
