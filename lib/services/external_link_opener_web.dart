import 'dart:html' as html;

Future<bool> openExternalLinkImpl(Uri uri) async {
  html.window.open(uri.toString(), '_blank');
  return true;
}
