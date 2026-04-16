import 'external_link_opener_stub.dart'
    if (dart.library.html) 'external_link_opener_web.dart';

Future<bool> openExternalLink(Uri uri) => openExternalLinkImpl(uri);
