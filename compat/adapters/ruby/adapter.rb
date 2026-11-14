# frozen_string_literal: true

# The Ruby adapter: one reader, one file, one JSON object on stdout (compat/README.md).
#
#   ruby adapter.rb <reader-id> <path> [--password P] [--delimiter D]
#
# What ships with Ruby, and no imports of this repository: the standard library, the default and
# bundled gems (csv and rexml load with a plain `require` on a fresh install, docs/07 section 8) and
# RubyGems' own tar reader. Each reader opens the file the way its own documentation shows, reads
# all of it, and reports only what the reader gives natively, under the manifest's names. Ruby has
# no standard-library reader for zip, images or WAV, so those formats have no reader here
# (compat/readers.yaml). A `require` that fails answers `no-reader`.
require 'json'
require 'openssl'
require 'zlib'

CHUNK = 1 << 16
ERROR_LIMIT = 200

def drain(stream)
  total = 0
  while (chunk = stream.read(CHUNK))
    total += chunk.bytesize
  end
  total
end

def gzip_reader(path, _delimiter)
  Zlib::GzipReader.open(path) { |gz| { 'uncompressed_bytes' => drain(gz) } }
end

def json_reader(path, _delimiter)
  value = JSON.parse(File.read(path, encoding: 'UTF-8'))
  names = { Hash => 'object', Array => 'array', String => 'string', TrueClass => 'boolean',
            FalseClass => 'boolean', NilClass => 'null' }
  report = { 'top_type' => names.fetch(value.class, 'number') }
  report['items'] = value.size if value.is_a?(Hash) || value.is_a?(Array)
  report
end

def csv_reader(path, delimiter)
  require 'csv'
  rows = CSV.read(path, col_sep: delimiter || ',', encoding: 'UTF-8')
  report = { 'rows' => rows.length }
  report['columns'] = rows.first.length unless rows.empty?
  report
end

def rexml_reader(path, _delimiter)
  require 'rexml/document'
  root = REXML::Document.new(File.read(path, encoding: 'UTF-8')).root
  report = {}
  return report if root.nil?

  report['root_element'] = root.name
  namespace = root.namespace.to_s
  report['root_namespace'] = namespace unless namespace.empty?
  report
end

def walk_tar(io)
  require 'rubygems/package'
  entries = directories = size = 0
  Gem::Package::TarReader.new(io) do |tar|
    tar.each do |entry|
      entries += 1
      directories += 1 if entry.directory?
      size += drain(entry)
    end
  end
  { 'entries' => entries, 'directories' => directories, 'uncompressed_bytes' => size }
end

def tar_reader(path, _delimiter)
  File.open(path, 'rb') { |file| walk_tar(file) }
end

# RubyGems' tar reader does not decompress, so a gzip-compressed tar is read through Zlib::GzipReader
# chained into it, and the gzip stream is then read to its end.
def tar_gzip_reader(path, _delimiter)
  File.open(path, 'rb') do |file|
    gz = Zlib::GzipReader.new(file)
    report = walk_tar(gz)
    drain(gz)
    report
  end
end

# A named exception (readers.yaml): the certificate's subject alternative names come as text,
# `DNS:a, DNS:b`, and the adapter takes the DNS entries from it.
def certificate_reader(path, _delimiter)
  cert = OpenSSL::X509::Certificate.new(File.binread(path))
  common = ->(name) { name.to_a.find { |type, _value, _kind| type == 'CN' }&.at(1) }
  alternative = cert.extensions.find { |extension| extension.oid == 'subjectAltName' }
  names = alternative ? alternative.value.split(/,\s*/).grep(/\ADNS:/).map { |entry| entry.sub('DNS:', '') } : []
  report = { 'serial' => cert.serial.to_i, 'dns_names' => names }
  subject = common.call(cert.subject)
  issuer = common.call(cert.issuer)
  report['subject_cn'] = subject unless subject.nil?
  report['issuer_cn'] = issuer unless issuer.nil?
  report
end

READERS = {
  'ruby/CSV' => method(:csv_reader),
  'ruby/Gem::Package::TarReader' => method(:tar_reader),
  'ruby/Gem::Package::TarReader+Zlib::GzipReader' => method(:tar_gzip_reader),
  'ruby/JSON' => method(:json_reader),
  'ruby/OpenSSL::X509::Certificate' => method(:certificate_reader),
  'ruby/REXML' => method(:rexml_reader),
  'ruby/Zlib::GzipReader' => method(:gzip_reader)
}.freeze

def sorted(value)
  case value
  when Hash then value.sort.to_h { |key, item| [key, sorted(item)] }
  when Array then value.map { |item| sorted(item) }
  else value
  end
end

def first_line(text)
  text.to_s.strip.lines.first.to_s.strip[0, ERROR_LIMIT]
end

def option(args, name)
  index = args.index(name)
  index ? args[index + 1] : nil
end

def main(args)
  reader_id, path = args
  if path.nil?
    warn 'usage: adapter.rb <reader-id> <path> [--password P] [--delimiter D]'
    return 2
  end
  reader = READERS[reader_id]
  if reader.nil?
    warn "unknown reader: #{reader_id}"
    return 2
  end
  result =
    begin
      { 'outcome' => 'reads', 'props' => reader.call(path, option(args, '--delimiter')) }
    rescue LoadError
      { 'outcome' => 'no-reader' }
    rescue StandardError, ScriptError => e
      { 'outcome' => 'refuses', 'error_type' => e.class.name, 'error' => first_line(e.message).then { |m| m.empty? ? e.class.name : m } }
    end
  puts JSON.generate(sorted(result))
  0
end

exit main(ARGV)
