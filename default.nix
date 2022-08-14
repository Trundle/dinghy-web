{ buildPythonPackage
, aiofiles
, aiohttp
, chameleon
, click-log
, emoji
, fetchFromGitHub
, glom
, hatchling
, jinja2
, lib
, pyyaml
, setuptools
}:

let
  dinghy = buildPythonPackage rec {
    pname = "dinghy";
    version = "0.13.2";

    src = fetchFromGitHub {
      owner = "nedbat";
      repo = pname;
      rev = version;
      sha256 = "sha256-uRiWcrs3xIb6zxNg0d6/+NCqnEgadHSTLpS53CoZ5so=";
    };

    propagatedBuildInputs = [
      aiofiles
      aiohttp
      click-log
      emoji
      glom
      jinja2
      pyyaml
    ];

    pythonImportsCheck = [ "dinghy.cli" ];
  };
in
buildPythonPackage {
  pname = "dinghy-web";
  version = "2022.8.1";
  format = "pyproject";

  src = ./.;

  buildInputs = [
    hatchling
  ];

  propagatedBuildInputs = [
    aiohttp
    chameleon
    dinghy
    # Really a chameleon dependency, but seems to be missing
    setuptools
  ];
}
