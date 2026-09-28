// Fetch one fixture and check it against the hash in the manifest. Standard library.
package main

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net/http"
)

const base, wanted = "https://loremfile.dev/", "pdf/minimal.pdf"

type manifest struct {
	Fixtures []struct {
		Path   string `json:"path"`
		SHA256 string `json:"sha256"`
	} `json:"fixtures"`
}

func get(url string) ([]byte, error) {
	response, err := http.Get(url)
	if err != nil {
		return nil, err
	}
	defer response.Body.Close()
	if response.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("%s answered %s", url, response.Status)
	}
	return io.ReadAll(response.Body)
}

func main() {
	raw, err := get(base + "manifest.json")
	if err != nil {
		log.Fatal(err)
	}
	var published manifest
	if err := json.Unmarshal(raw, &published); err != nil {
		log.Fatal(err)
	}
	want := ""
	for _, fixture := range published.Fixtures {
		if fixture.Path == wanted {
			want = fixture.SHA256
		}
	}
	body, err := get(base + wanted)
	if err != nil {
		log.Fatal(err)
	}
	sum := sha256.Sum256(body)
	if got := hex.EncodeToString(sum[:]); got != want {
		log.Fatalf("%s: got %s, the manifest says %s", wanted, got, want)
	}
	fmt.Printf("%s: %d bytes, sha256 matches\n", wanted, len(body))
}
