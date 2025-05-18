## Running

You can run script with docker or python

### Python
```shell
python main.py --config_file src/dict_typer/config_sample.toml
```

### Cmd
```shell
poetry install
poetry run dict_typer
```

### Docker
```shell
docker build -t DictTyper .
docker run -it DictTyper /bin/sh
python main.py
```
