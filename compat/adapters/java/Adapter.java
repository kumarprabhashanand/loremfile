// The Java adapter: one reader, one file, one JSON object on stdout (compat/README.md).
//
//   java Adapter <reader-id> <path> [--password P] [--delimiter D]
//
// The Java platform's own libraries only, and no imports of this repository. Written to compile as
// Java 8 so that every supported Temurin release builds the same file. Each reader opens the file
// the way its own documentation shows, reads all of it, and reports only what the reader gives
// natively, under the manifest's names. Java has no standard-library reader for tar, CSV or JSON,
// so those formats have no reader here (compat/readers.yaml). java.util.zip has no password
// support, so --password is accepted and unused.

import java.io.File;
import java.io.FileInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.math.BigInteger;
import java.security.cert.CertificateFactory;
import java.security.cert.X509Certificate;
import java.util.ArrayList;
import java.util.Collection;
import java.util.Enumeration;
import java.util.Iterator;
import java.util.List;
import java.util.Map;
import java.util.TreeMap;
import java.util.zip.GZIPInputStream;
import java.util.zip.ZipEntry;
import java.util.zip.ZipFile;
import javax.imageio.ImageIO;
import javax.imageio.ImageReader;
import javax.imageio.stream.ImageInputStream;
import javax.naming.ldap.LdapName;
import javax.naming.ldap.Rdn;
import javax.security.auth.x500.X500Principal;
import javax.sound.sampled.AudioFormat;
import javax.sound.sampled.AudioInputStream;
import javax.sound.sampled.AudioSystem;
import javax.xml.parsers.DocumentBuilderFactory;
import org.w3c.dom.Document;

public final class Adapter {
    private static final int CHUNK = 1 << 16;
    private static final int ERROR_LIMIT = 200;

    private interface Reader {
        Map<String, Object> read(File file) throws Exception;
    }

    private Adapter() {}

    /** Reads a stream to its end without keeping it; the number of bytes it held. */
    private static long drain(InputStream in) throws IOException {
        byte[] buffer = new byte[CHUNK];
        long total = 0;
        int n;
        while ((n = in.read(buffer)) != -1) {
            total += n;
        }
        return total;
    }

    private static Map<String, Object> zip(File file) throws Exception {
        long entries = 0;
        long directories = 0;
        long size = 0;
        try (ZipFile archive = new ZipFile(file)) {
            Enumeration<? extends ZipEntry> all = archive.entries();
            while (all.hasMoreElements()) {
                ZipEntry entry = all.nextElement();
                entries++;
                if (entry.isDirectory()) {
                    directories++;
                }
                try (InputStream in = archive.getInputStream(entry)) {
                    size += drain(in);
                }
            }
        }
        Map<String, Object> report = new TreeMap<>();
        report.put("entries", entries);
        report.put("directories", directories);
        report.put("uncompressed_bytes", size);
        return report;
    }

    private static Map<String, Object> gzip(File file) throws Exception {
        try (InputStream in = new GZIPInputStream(new FileInputStream(file))) {
            Map<String, Object> report = new TreeMap<>();
            report.put("uncompressed_bytes", drain(in));
            return report;
        }
    }

    private static Map<String, Object> image(File file) throws Exception {
        try (ImageInputStream in = ImageIO.createImageInputStream(file)) {
            if (in == null) {
                throw new IOException("ImageIO could not open the file as an image stream");
            }
            Iterator<ImageReader> readers = ImageIO.getImageReaders(in);
            if (!readers.hasNext()) {
                throw new IOException("no ImageReader accepted the file");
            }
            ImageReader reader = readers.next();
            try {
                reader.setInput(in);
                int frames = reader.getNumImages(true);
                for (int i = 0; i < frames; i++) {
                    reader.read(i);
                }
                Map<String, Object> report = new TreeMap<>();
                report.put("width", reader.getWidth(0));
                report.put("height", reader.getHeight(0));
                report.put("frames", frames);
                return report;
            } finally {
                reader.dispose();
            }
        }
    }

    private static Map<String, Object> wav(File file) throws Exception {
        try (AudioInputStream in = AudioSystem.getAudioInputStream(file)) {
            AudioFormat format = in.getFormat();
            long frames = in.getFrameLength();
            drain(in);
            Map<String, Object> report = new TreeMap<>();
            report.put("channels", format.getChannels());
            report.put("sample_rate", Math.round(format.getSampleRate()));
            report.put("bit_depth", format.getSampleSizeInBits());
            report.put("duration_ms", Math.round(frames * 1000.0 / format.getSampleRate()));
            return report;
        }
    }

    private static Map<String, Object> xml(File file) throws Exception {
        Document document = DocumentBuilderFactory.newInstance().newDocumentBuilder().parse(file);
        Map<String, Object> report = new TreeMap<>();
        report.put("root_element", document.getDocumentElement().getTagName());
        return report;
    }

    private static String commonName(X500Principal principal) throws Exception {
        for (Rdn rdn : new LdapName(principal.getName()).getRdns()) {
            if (rdn.getType().equalsIgnoreCase("CN")) {
                return rdn.getValue().toString();
            }
        }
        return null;
    }

    private static Map<String, Object> certificate(File file) throws Exception {
        try (InputStream in = new FileInputStream(file)) {
            X509Certificate cert =
                    (X509Certificate) CertificateFactory.getInstance("X.509").generateCertificate(in);
            Map<String, Object> report = new TreeMap<>();
            String subject = commonName(cert.getSubjectX500Principal());
            String issuer = commonName(cert.getIssuerX500Principal());
            if (subject != null) {
                report.put("subject_cn", subject);
            }
            if (issuer != null) {
                report.put("issuer_cn", issuer);
            }
            report.put("serial", cert.getSerialNumber());
            List<String> names = new ArrayList<>();
            Collection<List<?>> alternatives = cert.getSubjectAlternativeNames();
            if (alternatives != null) {
                for (List<?> alternative : alternatives) {
                    if (alternative.get(0) instanceof Integer && (Integer) alternative.get(0) == 2) {
                        names.add(String.valueOf(alternative.get(1)));
                    }
                }
            }
            report.put("dns_names", names);
            return report;
        }
    }

    private static Map<String, Reader> readers() {
        Map<String, Reader> all = new TreeMap<>();
        all.put("java/java.security.cert.CertificateFactory", Adapter::certificate);
        all.put("java/java.util.zip.GZIPInputStream", Adapter::gzip);
        all.put("java/java.util.zip.ZipFile", Adapter::zip);
        all.put("java/javax.imageio", Adapter::image);
        all.put("java/javax.sound.sampled", Adapter::wav);
        all.put("java/javax.xml.parsers", Adapter::xml);
        return all;
    }

    // --- JSON out: keys sorted, a BigInteger written as the number it is -------------------------

    private static void quote(StringBuilder out, String text) {
        out.append('"');
        for (int i = 0; i < text.length(); i++) {
            char c = text.charAt(i);
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
        out.append('"');
    }

    private static void emit(StringBuilder out, Object value) {
        if (value == null) {
            out.append("null");
        } else if (value instanceof Map) {
            out.append('{');
            boolean first = true;
            for (Map.Entry<?, ?> e : new TreeMap<Object, Object>((Map<?, ?>) value).entrySet()) {
                if (!first) {
                    out.append(',');
                }
                first = false;
                quote(out, String.valueOf(e.getKey()));
                out.append(':');
                emit(out, e.getValue());
            }
            out.append('}');
        } else if (value instanceof List) {
            out.append('[');
            boolean first = true;
            for (Object item : (List<?>) value) {
                if (!first) {
                    out.append(',');
                }
                first = false;
                emit(out, item);
            }
            out.append(']');
        } else if (value instanceof Number || value instanceof Boolean || value instanceof BigInteger) {
            out.append(value);
        } else {
            quote(out, String.valueOf(value));
        }
    }

    private static String firstLine(String text) {
        String trimmed = text == null ? "" : text.trim();
        int newline = trimmed.indexOf('\n');
        String line = newline < 0 ? trimmed : trimmed.substring(0, newline);
        return line.length() > ERROR_LIMIT ? line.substring(0, ERROR_LIMIT) : line;
    }

    public static void main(String[] args) {
        if (args.length < 2) {
            System.err.println("usage: Adapter <reader-id> <path> [--password P] [--delimiter D]");
            System.exit(2);
        }
        Reader reader = readers().get(args[0]);
        if (reader == null) {
            System.err.println("unknown reader: " + args[0]);
            System.exit(2);
        }
        Map<String, Object> result = new TreeMap<>();
        try {
            result.put("props", reader.read(new File(args[1])));
            result.put("outcome", "reads");
        } catch (Throwable error) {
            result.clear();
            String message = firstLine(error.getMessage());
            result.put("outcome", "refuses");
            result.put("error_type", error.getClass().getName());
            result.put("error", message.isEmpty() ? error.getClass().getName() : message);
        }
        StringBuilder out = new StringBuilder();
        emit(out, result);
        System.out.println(out);
        System.out.flush();
        System.exit(0);
    }
}
