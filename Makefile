DST=/local/pydownloader-test
PKGS=pyyaml urwid clg unix
FILES=ddl pydownloader cmd.yml

all: clean virtualenv install

clean:
	rm -rf $(DST) 2> /dev/null

virtualenv:
	virtualenv $(DST)/env --prompt "(pydownloader)"
	$(DST)/env/bin/pip install --upgrade pip
	$(DST)/env/bin/pip install $(PKGS)

install:
	cp -rf $(FILES) $(DST)
