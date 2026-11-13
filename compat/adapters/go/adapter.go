// The Go adapter: one reader, one file, one JSON object on stdout (compat/README.md).
//
//	adapter <reader-id> <path> [--password P] [--delimiter D]
//
// Standard library only. Each reader opens the file the way its own documentation shows, reads
// all of it, and reports only what the reader gives natively, under the manifest's names.
// Go's archive/zip has no way to give a password, so --password is accepted and unused.
package main

import (
	"archive/tar"
	"archive/zip"
	"compress/gzip"
	"crypto/x509"
	"encoding/csv"
	"encoding/json"
	"encoding/pem"
	"encoding/xml"
	"errors"
	"fmt"
	"image"
	"image/gif"
	"image/jpeg"
	"image/png"
	"io"
	"os"
	"strings"
)

const errorLimit = 200

type props = map[string]any

// counter counts what is copied into it and keeps none of it.
type counter int64

func (c *counter) Write(p []byte) (int, error) {
	*c += counter(len(p))
	return len(p), nil
}

func drain(r io.Reader) (int64, error) {
	var n counter
	_, err := io.Copy(&n, r)
	return int64(n), err
}

func readZip(path, _, _ string) (props, error) {
	archive, err := zip.OpenReader(path)
	if err != nil {
		return nil, err
	}
	defer archive.Close()
	var entries, directories, size int64
	for _, f := range archive.File {
		entries++
		if f.FileInfo().IsDir() {
			directories++
		}
		member, err := f.Open()
		if err != nil {
			return nil, err
		}
		n, err := drain(member)
		member.Close()
		if err != nil {
			return nil, err
		}
		size += n
	}
	return props{"entries": entries, "directories": directories, "uncompressed_bytes": size}, nil
}

func readTar(path, _, _ string) (props, error) {
	file, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	defer file.Close()
	return walkTar(file)
}

// readTarGzip chains compress/gzip into archive/tar, the arrangement the archive/tar documentation
// describes for a compressed archive: archive/tar itself does not decompress. The gzip stream is
// then read to its end, so that its checksum is verified too.
func readTarGzip(path, _, _ string) (props, error) {
	file, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	defer file.Close()
	stream, err := gzip.NewReader(file)
	if err != nil {
		return nil, err
	}
	report, err := walkTar(stream)
	if err != nil {
		return nil, err
	}
	if _, err := drain(stream); err != nil {
		return nil, err
	}
	return report, nil
}

func walkTar(source io.Reader) (props, error) {
	archive := tar.NewReader(source)
	var entries, directories, size int64
	for {
		header, err := archive.Next()
		if err == io.EOF {
			break
		}
		if err != nil {
			return nil, err
		}
		entries++
		if header.Typeflag == tar.TypeDir {
			directories++
		}
		n, err := drain(archive)
		if err != nil {
			return nil, err
		}
		size += n
	}
	return props{"entries": entries, "directories": directories, "uncompressed_bytes": size}, nil
}

func readGzip(path, _, _ string) (props, error) {
	file, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	defer file.Close()
	stream, err := gzip.NewReader(file)
	if err != nil {
		return nil, err
	}
	size, err := drain(stream)
	if err != nil {
		return nil, err
	}
	return props{"uncompressed_bytes": size}, nil
}

func readJPEG(path, _, _ string) (props, error) {
	file, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	defer file.Close()
	img, err := jpeg.Decode(file)
	if err != nil {
		return nil, err
	}
	return bounds(img), nil
}

func readPNG(path, _, _ string) (props, error) {
	file, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	defer file.Close()
	img, err := png.Decode(file)
	if err != nil {
		return nil, err
	}
	return bounds(img), nil
}

func bounds(img image.Image) props {
	b := img.Bounds()
	return props{"width": b.Dx(), "height": b.Dy()}
}

func readGIF(path, _, _ string) (props, error) {
	file, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	defer file.Close()
	all, err := gif.DecodeAll(file)
	if err != nil {
		return nil, err
	}
	return props{"width": all.Config.Width, "height": all.Config.Height, "frames": len(all.Image)}, nil
}

func readJSON(path, _, _ string) (props, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	var value any
	if err := json.Unmarshal(data, &value); err != nil {
		return nil, err
	}
	switch v := value.(type) {
	case map[string]any:
		return props{"top_type": "object", "items": len(v)}, nil
	case []any:
		return props{"top_type": "array", "items": len(v)}, nil
	case string:
		return props{"top_type": "string"}, nil
	case bool:
		return props{"top_type": "boolean"}, nil
	case nil:
		return props{"top_type": "null"}, nil
	}
	return props{"top_type": "number"}, nil
}

func readCSV(path, _, delimiter string) (props, error) {
	file, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	defer file.Close()
	reader := csv.NewReader(file)
	if delimiter != "" {
		reader.Comma = []rune(delimiter)[0]
	}
	rows, err := reader.ReadAll()
	if err != nil {
		return nil, err
	}
	report := props{"rows": len(rows)}
	if len(rows) > 0 {
		report["columns"] = len(rows[0])
	}
	return report, nil
}

func readXML(path, _, _ string) (props, error) {
	file, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	defer file.Close()
	decoder := xml.NewDecoder(file)
	root, namespace := "", ""
	for {
		token, err := decoder.Token()
		if err == io.EOF {
			break
		}
		if err != nil {
			return nil, err
		}
		if start, ok := token.(xml.StartElement); ok && root == "" {
			root, namespace = start.Name.Local, start.Name.Space
		}
	}
	report := props{}
	if root != "" {
		report["root_element"] = root
	}
	if namespace != "" {
		report["root_namespace"] = namespace
	}
	return report, nil
}

// readCertificate takes a PEM or a DER file: PEM through encoding/pem first, as x509's own
// documentation does, DER straight to ParseCertificate.
func readCertificate(path, _, _ string) (props, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	if strings.HasSuffix(path, ".pem") {
		block, _ := pem.Decode(data)
		if block == nil {
			return nil, errors.New("no PEM data found")
		}
		data = block.Bytes
	}
	cert, err := x509.ParseCertificate(data)
	if err != nil {
		return nil, err
	}
	names := cert.DNSNames
	if names == nil {
		names = []string{}
	}
	return props{
		"subject_cn": cert.Subject.CommonName,
		"issuer_cn":  cert.Issuer.CommonName,
		"serial":     cert.SerialNumber,
		"dns_names":  names,
	}, nil
}

var readers = map[string]func(path, password, delimiter string) (props, error){
	"go/archive/tar":               readTar,
	"go/archive/tar+compress/gzip": readTarGzip,
	"go/archive/zip":               readZip,
	"go/compress/gzip":             readGzip,
	"go/crypto/x509":               readCertificate,
	"go/encoding/csv":              readCSV,
	"go/encoding/json":             readJSON,
	"go/encoding/xml":              readXML,
	"go/image/gif":                 readGIF,
	"go/image/jpeg":                readJPEG,
	"go/image/png":                 readPNG,
}

func option(args []string, name string) string {
	for i, a := range args {
		if a == name && i+1 < len(args) {
			return args[i+1]
		}
	}
	return ""
}

func firstLine(text string) string {
	line, _, _ := strings.Cut(strings.TrimSpace(text), "\n")
	if len(line) > errorLimit {
		line = line[:errorLimit]
	}
	return line
}

func main() {
	args := os.Args[1:]
	if len(args) < 2 {
		fmt.Fprintln(os.Stderr, "usage: adapter <reader-id> <path> [--password P] [--delimiter D]")
		os.Exit(2)
	}
	read, ok := readers[args[0]]
	if !ok {
		fmt.Fprintln(os.Stderr, "unknown reader:", args[0])
		os.Exit(2)
	}
	report, err := read(args[1], option(args, "--password"), option(args, "--delimiter"))
	var result props
	if err != nil {
		message := firstLine(err.Error())
		if message == "" {
			message = fmt.Sprintf("%T", err)
		}
		result = props{"outcome": "refuses", "error_type": strings.TrimPrefix(fmt.Sprintf("%T", err), "*"), "error": message}
	} else {
		result = props{"outcome": "reads", "props": report}
	}
	out, marshalErr := json.Marshal(result)
	if marshalErr != nil {
		fmt.Fprintln(os.Stderr, marshalErr)
		os.Exit(1)
	}
	fmt.Println(string(out))
}
