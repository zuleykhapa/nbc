#!/bin/bash

release_v="v1.2.0"
sha="5d02d69e5c"
platform=("osx" "linux")
arch=("arm64" "amd64")
extensions=('arrow' 'autocomplete' 'aws' 'azure' 'delta' 'excel' 'fts' 'httpfs' 'iceberg' 'icu' 'inet' 'jemalloc' 'json' 'motherduck' 'mysql_scanner' 'parquet' 'postgres_scanner' 'shell' 'spatial' 'sqlite_scanner' 'sqlsmith' 'substrait' 'tpcds' 'tpch' 'vss')
for pl in ${platform[@]}; do
    for ar in ${arch[@]}; do
        for ext in ${extensions[@]}; do
            wget https://duckdb-extensions.s3.us-east-2.amazonaws.com/${release_v}/${platform}_${arch}/${ext}.duckdb_extension.gz
            gzip -d ${ext}.duckdb_extension.gz
            hexdump -C ${ext}.duckdb_extension | tail -n 30 | awk -F'|' '{print $2}' | tr -d '\n' > ${ext}-${sha}-${platform}-${arch}.txt
            if $(cat ${ext}-${sha}-${platform}-${arch}.txt | grep -o $release_v); then
                echo "${ext},${sha},${platform},${arch},passed"
                echo "${ext},${sha},${platform},${arch},passed" >> log.csv
            else
                echo "${ext},${sha},${platform},${arch},failed"
                echo "${ext},${sha},${platform},${arch},failed" >> log.csv
            fi
            rm ${ext}.duckdb_extension
            rm ${ext}-${sha}-${platform}-${arch}.txt
        done
    done
done