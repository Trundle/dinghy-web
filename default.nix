{ buildPythonPackage
, aiohttp
, chameleon
, dinghy
, hatchling
, lib
, setuptools
}:

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
