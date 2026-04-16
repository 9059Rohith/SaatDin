import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';

import '../models/user_model.dart';
import '../models/claim_model.dart';
import '../models/plan_model.dart';
import '../models/platform_model.dart';
import '../models/zone_risk_model.dart';
import 'zone_risk_service.dart';

class WorkerStatus {
  const WorkerStatus({required this.phone, required this.exists, this.worker});

  final String phone;
  final bool exists;
  final User? worker;
}

class ApiService {
  static String get baseUrl => _candidateBaseUrls.first;
  static List<String> get _candidateBaseUrls {
    const configuredBaseUrl = String.fromEnvironment('API_BASE_URL');
    if (configuredBaseUrl.isNotEmpty) {
      return [configuredBaseUrl];
    }

    const productionBaseUrl = 'https://saatdin.onrender.com/api/v1';

    if (kIsWeb) {
      return const [
        productionBaseUrl,
        'http://localhost:8000/api/v1',
        'http://localhost:8005/api/v1',
      ];
    }

    if (defaultTargetPlatform == TargetPlatform.android) {
      return const [
        'http://10.0.2.2:8000/api/v1',
        'http://10.0.2.2:8005/api/v1',
        productionBaseUrl,
      ];
    }

    return const [
      productionBaseUrl,
      'http://localhost:8000/api/v1',
      'http://localhost:8005/api/v1',
    ];
  }

  static final ZoneRiskService _zoneRiskService = ZoneRiskService();
  static const Duration _timeout = Duration(seconds: 8);
  static const String _tokenStorageKey = 'saatdin_access_token';
  String? _accessToken;
  String? _lastError;
  bool _sessionInitialized = false;

  // Singleton
  static final ApiService _instance = ApiService._internal();
  factory ApiService() => _instance;
  ApiService._internal();

  Map<String, String> _headers({bool authorized = false}) {
    final headers = <String, String>{'Content-Type': 'application/json'};
    if (authorized && _accessToken != null) {
      headers['Authorization'] = 'Bearer $_accessToken';
    }
    return headers;
  }

  dynamic _extractData(Map<String, dynamic> body) {
    if (body.containsKey('success')) {
      if (body['success'] == true) {
        return body['data'];
      }
      return null;
    }
    return body;
  }

  bool get isAuthenticated => _accessToken != null;
  String? get lastError => _lastError;

  String normalizePhoneNumber(String raw) {
    final digitsOnly = raw.replaceAll(RegExp(r'\D'), '');
    if (digitsOnly.length == 10) return digitsOnly;
    if (digitsOnly.length == 11 && digitsOnly.startsWith('0')) {
      return digitsOnly.substring(1);
    }
    if (digitsOnly.length == 12 && digitsOnly.startsWith('91')) {
      return digitsOnly.substring(2);
    }
    return digitsOnly;
  }

  Future<void> initializeSession() async {
    final prefs = await SharedPreferences.getInstance();
    final token = prefs.getString(_tokenStorageKey)?.trim();
    if (token != null && token.isNotEmpty) {
      _accessToken = token;
    }
    _sessionInitialized = true;
  }

  Future<void> _ensureSessionInitialized() async {
    if (_sessionInitialized) return;
    try {
      await initializeSession();
    } catch (_) {
      // Keep calls resilient in contexts where storage is temporarily unavailable.
      _sessionInitialized = true;
    }
  }

  Future<void> _persistSessionToken(String token) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_tokenStorageKey, token);
  }

  Future<void> clearSession() async {
    _accessToken = null;
    _sessionInitialized = true;
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove(_tokenStorageKey);
  }

  String _messageFromBody(
    Map<String, dynamic> body, {
    required String fallback,
  }) {
    final message = body['message'];
    final detail = body['detail'];
    if (message is String && message.trim().isNotEmpty) return message;
    if (detail is String && detail.trim().isNotEmpty) return detail;
    return fallback;
  }

  // ── Auth ──────────────────────────────────────────

  /// POST /auth/send-otp
  Future<bool> sendOtp(String phoneNumber) async {
    _lastError = null;
    final normalizedPhone = normalizePhoneNumber(phoneNumber);
    final errors = <String>[];

    for (final candidate in _candidateBaseUrls) {
      try {
        final uri = Uri.parse('$candidate/auth/send-otp');
        final response = await http
            .post(
              uri,
              headers: _headers(),
              body: jsonEncode({'phoneNumber': normalizedPhone}),
            )
            .timeout(_timeout);

        if (response.statusCode == 200) {
          final data = jsonDecode(response.body) as Map<String, dynamic>;
          if (data['success'] == true) {
            return true;
          }
          errors.add(_messageFromBody(data, fallback: 'OTP send failed.'));
          continue;
        }

        final dynamic decoded = jsonDecode(response.body);
        if (decoded is Map<String, dynamic>) {
          errors.add(
            _messageFromBody(
              decoded,
              fallback: 'Request failed (${response.statusCode}).',
            ),
          );
        } else {
          errors.add('Request failed (${response.statusCode}).');
        }
      } catch (_) {
        errors.add('Could not reach server at $candidate');
      }
    }

    if (errors.isNotEmpty) {
      _lastError = errors.first;
    }
    return false;
  }

  /// POST /auth/verify-otp
  Future<bool> verifyOtp(String phoneNumber, String otp) async {
    _lastError = null;
    final normalizedPhone = normalizePhoneNumber(phoneNumber);
    final errors = <String>[];

    for (final candidate in _candidateBaseUrls) {
      try {
        final uri = Uri.parse('$candidate/auth/verify-otp');
        final response = await http
            .post(
              uri,
              headers: _headers(),
              body: jsonEncode({'phoneNumber': normalizedPhone, 'otp': otp}),
            )
            .timeout(_timeout);
        if (response.statusCode == 200) {
          final data = jsonDecode(response.body) as Map<String, dynamic>;
          final payload = _extractData(data) as Map<String, dynamic>?;
          final token = (payload?['token'] as String?)?.trim();
          if (token != null && token.isNotEmpty) {
            _accessToken = token;
            await _persistSessionToken(token);
            return true;
          }
          errors.add('Invalid authentication response from $candidate');
          continue;
        }

        final dynamic decoded = jsonDecode(response.body);
        if (decoded is Map<String, dynamic>) {
          errors.add(
            _messageFromBody(
              decoded,
              fallback: 'Verification failed (${response.statusCode}).',
            ),
          );
        } else {
          errors.add('Verification failed (${response.statusCode}).');
        }
      } catch (_) {
        errors.add('Could not reach server at $candidate');
      }
    }

    if (errors.isNotEmpty) {
      _lastError = errors.first;
    }
    return false;
  }

  // ── Registration ──────────────────────────────────

  /// POST /register
  Future<User?> registerUser({
    required String phone,
    required String platformName,
    required String zone,
    required String planName,
    String? name,
  }) async {
    await _ensureSessionInitialized();
    if (_accessToken == null) return null;

    try {
      final uri = Uri.parse('$baseUrl/register');
      final normalizedPhone = normalizePhoneNumber(phone);
      final response = await http
          .post(
            uri,
            headers: _headers(authorized: true),
            body: jsonEncode({
              'phone': normalizedPhone,
              'platformName': platformName,
              'zone': zone,
              'planName': planName,
              if (name != null && name.trim().isNotEmpty) 'name': name.trim(),
            }),
          )
          .timeout(_timeout);
      if (response.statusCode == 200 || response.statusCode == 201) {
        final body = jsonDecode(response.body) as Map<String, dynamic>;
        final payload = _extractData(body) as Map<String, dynamic>?;
        if (payload != null) {
          return User.fromJson(payload);
        }
      }
    } catch (_) {
      return null;
    }

    return null;
  }

  // ── Platforms ─────────────────────────────────────

  /// GET /platforms
  Future<List<DeliveryPlatform>> getPlatforms() async {
    await _ensureSessionInitialized();
    if (_accessToken == null) {
      throw Exception('Authentication required. Please verify OTP first.');
    }

    try {
      final uri = Uri.parse('$baseUrl/platforms');
      final response = await http
          .get(uri, headers: _headers(authorized: true))
          .timeout(_timeout);
      if (response.statusCode == 200) {
        final body = jsonDecode(response.body) as Map<String, dynamic>;
        final payload = _extractData(body);
        if (payload is List<dynamic>) {
          final mapped = <DeliveryPlatform>[];
          for (final item in payload) {
            final raw =
                (item as Map<String, dynamic>)['name']?.toString() ?? '';
            final normalized = raw.toLowerCase();
            final defaults = DeliveryPlatform.getPlatforms();
            if (normalized.contains('blinkit')) {
              mapped.add(defaults[0]);
            } else if (normalized.contains('zepto')) {
              mapped.add(defaults[1]);
            } else if (normalized.contains('swiggy')) {
              mapped.add(defaults[2]);
            }
          }
          if (mapped.isNotEmpty) return mapped;
        }
        throw Exception('Backend returned no platforms.');
      }
      final body = jsonDecode(response.body) as Map<String, dynamic>;
      throw Exception(
        _messageFromBody(body, fallback: 'Failed to fetch platforms.'),
      );
    } catch (_) {
      rethrow;
    }
  }

  // ── Plans ─────────────────────────────────────────

  /// GET /plans?zone={zone}&platform={platform}
  Future<List<InsurancePlan>> getPlans({
    required String zone,
    required String platform,
  }) async {
    await _ensureSessionInitialized();
    if (_accessToken == null) {
      throw Exception('Authentication required. Please verify OTP first.');
    }

    try {
      final uri = Uri.parse(
        '$baseUrl/plans',
      ).replace(queryParameters: {'zone': zone, 'platform': platform});
      final response = await http
          .get(uri, headers: _headers(authorized: true))
          .timeout(_timeout);
      if (response.statusCode == 200) {
        final body = jsonDecode(response.body) as Map<String, dynamic>;
        final raw = _extractData(body) as List<dynamic>?;
        if (raw == null) {
          throw Exception(
            'Backend returned no plans for selected zone/platform.',
          );
        }
        return raw
            .map((e) => InsurancePlan.fromJson(e as Map<String, dynamic>))
            .toList();
      }
      final body = jsonDecode(response.body) as Map<String, dynamic>;
      throw Exception(
        _messageFromBody(body, fallback: 'Failed to fetch plans.'),
      );
    } catch (_) {
      rethrow;
    }
  }

  /// GET /zones
  Future<List<ZoneRisk>> getZones() async {
    await _ensureSessionInitialized();
    if (_accessToken == null) {
      throw Exception('Authentication required. Please verify OTP first.');
    }

    try {
      final uri = Uri.parse('$baseUrl/zones');
      final response = await http
          .get(uri, headers: _headers(authorized: true))
          .timeout(_timeout);
      if (response.statusCode == 200) {
        final body = jsonDecode(response.body) as Map<String, dynamic>;
        final raw = _extractData(body) as List<dynamic>?;
        if (raw == null) {
          throw Exception('Backend returned no zones.');
        }
        return raw
            .map((e) => ZoneRisk.fromApiJson(e as Map<String, dynamic>))
            .toList();
      }
      final body = jsonDecode(response.body) as Map<String, dynamic>;
      throw Exception(
        _messageFromBody(body, fallback: 'Failed to fetch zones.'),
      );
    } catch (_) {
      rethrow;
    }
  }

  /// GET /zones?platform={platform}
  Future<List<ZoneRisk>> getZonesForPlatform(String platform) async {
    await _ensureSessionInitialized();
    if (_accessToken == null) {
      throw Exception('Authentication required. Please verify OTP first.');
    }

    try {
      final uri = Uri.parse(
        '$baseUrl/zones',
      ).replace(queryParameters: {'platform': platform});
      final response = await http
          .get(uri, headers: _headers(authorized: true))
          .timeout(_timeout);
      if (response.statusCode == 200) {
        final body = jsonDecode(response.body) as Map<String, dynamic>;
        final raw = _extractData(body) as List<dynamic>?;
        if (raw == null) {
          throw Exception(
            'Backend returned no zones for the selected platform.',
          );
        }
        return raw
            .map((e) => ZoneRisk.fromApiJson(e as Map<String, dynamic>))
            .toList();
      }
      final body = jsonDecode(response.body) as Map<String, dynamic>;
      throw Exception(
        _messageFromBody(body, fallback: 'Failed to fetch platform zones.'),
      );
    } catch (_) {
      rethrow;
    }
  }

  /// GET /zones/{pincode}/multiplier
  Future<double?> getZoneMultiplier(String pincode) async {
    return _zoneRiskService.getMultiplier(pincode);
  }

  // ── Policy ────────────────────────────────────────

  /// GET /policy/me
  Future<Map<String, dynamic>> getPolicy(String userId) async {
    await _ensureSessionInitialized();
    if (_accessToken == null) {
      throw Exception('Authentication required. Please verify OTP first.');
    }

    try {
      final uri = Uri.parse('$baseUrl/policy/me');
      final response = await http
          .get(uri, headers: _headers(authorized: true))
          .timeout(_timeout);
      if (response.statusCode == 200) {
        final body = jsonDecode(response.body) as Map<String, dynamic>;
        final payload = _extractData(body) as Map<String, dynamic>?;
        if (payload != null) return payload;
      }
      final body = jsonDecode(response.body) as Map<String, dynamic>;
      throw Exception(
        _messageFromBody(body, fallback: 'Failed to fetch policy.'),
      );
    } catch (_) {
      rethrow;
    }
  }

  /// PUT /policy/plan
  Future<Map<String, dynamic>> updatePolicyPlan(String planName) async {
    await _ensureSessionInitialized();
    if (_accessToken == null) {
      throw Exception('Authentication required. Please verify OTP first.');
    }

    try {
      final uri = Uri.parse('$baseUrl/policy/plan');
      final response = await http
          .put(
            uri,
            headers: _headers(authorized: true),
            body: jsonEncode({'planName': planName}),
          )
          .timeout(_timeout);
      if (response.statusCode == 200) {
        final body = jsonDecode(response.body) as Map<String, dynamic>;
        final payload = _extractData(body) as Map<String, dynamic>?;
        if (payload != null) return payload;
      }
      final body = jsonDecode(response.body) as Map<String, dynamic>;
      throw Exception(
        _messageFromBody(body, fallback: 'Failed to update policy plan.'),
      );
    } catch (_) {
      rethrow;
    }
  }

  // ── Claims ────────────────────────────────────────

  String _claimTypeToApi(ClaimType type) {
    switch (type) {
      case ClaimType.rainLock:
        return 'RainLock';
      case ClaimType.aqiGuard:
        return 'AQI Guard';
      case ClaimType.trafficBlock:
        return 'TrafficBlock';
      case ClaimType.zoneLock:
        return 'ZoneLock';
      case ClaimType.heatBlock:
        return 'HeatBlock';
    }
  }

  ClaimType _claimTypeFromApi(String value) {
    final normalized = value.trim().toLowerCase().replaceAll(' ', '');
    switch (normalized) {
      case 'rainlock':
        return ClaimType.rainLock;
      case 'aqiguard':
        return ClaimType.aqiGuard;
      case 'trafficblock':
        return ClaimType.trafficBlock;
      case 'zonelock':
        return ClaimType.zoneLock;
      case 'heatblock':
        return ClaimType.heatBlock;
      default:
        return ClaimType.trafficBlock;
    }
  }

  ClaimStatus _claimStatusFromApi(String value) {
    switch (value.trim().toLowerCase()) {
      case 'pending':
        return ClaimStatus.pending;
      case 'in_review':
      case 'inreview':
        return ClaimStatus.inReview;
      case 'settled':
        return ClaimStatus.settled;
      case 'rejected':
        return ClaimStatus.rejected;
      default:
        return ClaimStatus.pending;
    }
  }

  String _readString(
    Map<String, dynamic> raw,
    List<String> keys, {
    String fallback = '',
  }) {
    for (final key in keys) {
      final value = raw[key];
      if (value == null) continue;
      final parsed = value.toString().trim();
      if (parsed.isNotEmpty) return parsed;
    }
    return fallback;
  }

  double _readDouble(
    Map<String, dynamic> raw,
    List<String> keys, {
    double fallback = 0,
  }) {
    for (final key in keys) {
      final value = raw[key];
      if (value == null) continue;
      if (value is num) return value.toDouble();
      if (value is String) {
        final normalized = value.replaceAll(',', '').trim();
        final parsed = double.tryParse(normalized);
        if (parsed != null) return parsed;
      }
    }
    return fallback;
  }

  Claim _claimFromApi(Map<String, dynamic> raw) {
    final id = _readString(raw, const ['id', 'claimId', 'claim_id']);
    final normalizedId = id.isEmpty ? '' : (id.startsWith('#') ? id : '#$id');

    return Claim(
      id: normalizedId,
      type: _claimTypeFromApi(
        _readString(raw, const ['claimType', 'claim_type']),
      ),
      status: _claimStatusFromApi(_readString(raw, const ['status'])),
      amount: _readDouble(raw, const [
        'amount',
        'payoutAmount',
        'payout_amount',
      ]),
      date:
          DateTime.tryParse(
            _readString(raw, const ['date', 'createdAt', 'created_at']),
          ) ??
          DateTime.now(),
      description: _readString(raw, const ['description']),
    );
  }

  /// GET /claims
  Future<List<Claim>> getClaims(String userId) async {
    await _ensureSessionInitialized();
    if (_accessToken == null) {
      throw Exception('Authentication required. Please verify OTP first.');
    }

    try {
      final uri = Uri.parse('$baseUrl/claims');
      final response = await http
          .get(uri, headers: _headers(authorized: true))
          .timeout(_timeout);
      if (response.statusCode == 200) {
        final body = jsonDecode(response.body) as Map<String, dynamic>;
        final payload = _extractData(body) as List<dynamic>?;
        if (payload != null) {
          return payload
              .map((item) => _claimFromApi(item as Map<String, dynamic>))
              .toList();
        }
      }
      final body = jsonDecode(response.body) as Map<String, dynamic>;
      throw Exception(
        _messageFromBody(body, fallback: 'Failed to fetch claims.'),
      );
    } catch (_) {
      rethrow;
    }
  }

  /// POST /claims/submit
  Future<Claim> submitClaim({
    required String userId,
    required ClaimType type,
    required String description,
  }) async {
    await _ensureSessionInitialized();
    if (_accessToken == null) {
      throw Exception('Authentication required. Please verify OTP first.');
    }

    try {
      final uri = Uri.parse('$baseUrl/claims/submit');
      final response = await http
          .post(
            uri,
            headers: _headers(authorized: true),
            body: jsonEncode({
              'claimType': _claimTypeToApi(type),
              'description': description,
            }),
          )
          .timeout(_timeout);

      if (response.statusCode == 200 || response.statusCode == 201) {
        final body = jsonDecode(response.body) as Map<String, dynamic>;
        final payload = _extractData(body) as Map<String, dynamic>?;
        if (payload != null) return _claimFromApi(payload);
      }

      final body = jsonDecode(response.body) as Map<String, dynamic>;
      throw Exception(
        _messageFromBody(body, fallback: 'Failed to submit claim.'),
      );
    } catch (_) {
      rethrow;
    }
  }

  // ── Profile ───────────────────────────────────────

  /// GET /workers/me
  Future<User> getProfile(String userId) async {
    await _ensureSessionInitialized();
    if (_accessToken == null) {
      throw Exception('Authentication required. Please verify OTP first.');
    }

    try {
      final uri = Uri.parse('$baseUrl/workers/me');
      final response = await http
          .get(uri, headers: _headers(authorized: true))
          .timeout(_timeout);
      if (response.statusCode == 200) {
        final body = jsonDecode(response.body) as Map<String, dynamic>;
        final payload = _extractData(body) as Map<String, dynamic>?;
        if (payload != null) {
          return User.fromJson(payload);
        }
      }
      final body = jsonDecode(response.body) as Map<String, dynamic>;
      throw Exception(
        _messageFromBody(body, fallback: 'Failed to fetch profile.'),
      );
    } catch (_) {
      rethrow;
    }
  }

  Future<WorkerStatus> getWorkerStatus() async {
    await _ensureSessionInitialized();
    if (_accessToken == null) {
      return const WorkerStatus(phone: '', exists: false, worker: null);
    }

    try {
      final uri = Uri.parse('$baseUrl/workers/status');
      final response = await http
          .get(uri, headers: _headers(authorized: true))
          .timeout(_timeout);

      if (response.statusCode == 401 || response.statusCode == 403) {
        await clearSession();
        return const WorkerStatus(phone: '', exists: false, worker: null);
      }

      if (response.statusCode == 200) {
        final body = jsonDecode(response.body) as Map<String, dynamic>;
        final payload = _extractData(body) as Map<String, dynamic>?;
        if (payload != null) {
          final phone = (payload['phone'] as String? ?? '').trim();
          final exists = payload['exists'] == true;
          final workerPayload = payload['worker'];
          if (exists && workerPayload is Map<String, dynamic>) {
            return WorkerStatus(
              phone: phone,
              exists: true,
              worker: User.fromJson(workerPayload),
            );
          }
          return WorkerStatus(phone: phone, exists: false, worker: null);
        }
      }
    } catch (_) {
      // Let caller handle fallback UI.
    }

    return const WorkerStatus(phone: '', exists: false, worker: null);
  }

  /// PUT /profile/{userId}
  Future<User> updateProfile(String userId, Map<String, dynamic> data) async {
    // TODO: Connect to FastAPI
    await Future.delayed(const Duration(milliseconds: 500));
    return User.getMockUser();
  }

  // ── Triggers / Risk ───────────────────────────────

  /// GET /triggers/active?zone={zone}
  Future<Map<String, dynamic>> getActiveTriggers(String zone) async {
    await _ensureSessionInitialized();
    if (_accessToken == null) {
      throw Exception('Authentication required. Please verify OTP first.');
    }

    try {
      final uri = Uri.parse(
        '$baseUrl/triggers/active',
      ).replace(queryParameters: {'zone': zone});
      final response = await http
          .get(uri, headers: _headers(authorized: true))
          .timeout(_timeout);
      if (response.statusCode == 200) {
        final body = jsonDecode(response.body) as Map<String, dynamic>;
        final payload = _extractData(body) as Map<String, dynamic>?;
        if (payload != null) return payload;
      }
      final body = jsonDecode(response.body) as Map<String, dynamic>;
      throw Exception(
        _messageFromBody(body, fallback: 'Failed to fetch active triggers.'),
      );
    } catch (_) {
      rethrow;
    }
  }
}
