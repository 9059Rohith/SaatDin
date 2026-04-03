import 'package:flutter/material.dart';
import 'dart:math' as math;

import '../../theme/app_colors.dart';
import '../../models/claim_model.dart';
import '../../models/user_model.dart';
import '../../services/api_service.dart';
import '../../widgets/claim_card.dart';
import '../../services/tab_router.dart';

class ClaimsScreen extends StatefulWidget {
  const ClaimsScreen({super.key});

  @override
  State<ClaimsScreen> createState() => _ClaimsScreenState();
}

class _ClaimsScreenState extends State<ClaimsScreen> {
  final ApiService _apiService = ApiService();
  int _selectedTab = 0;
  final _tabs = ['All Claims', 'In Review', 'Settled'];
  List<Claim> _claims = [];
  User? _user;
  Map<String, dynamic>? _policy;
  bool _isLoadingClaims = true;

  @override
  void initState() {
    super.initState();
    _loadClaims();
  }

  Future<void> _loadClaims() async {
    setState(() {
      _isLoadingClaims = true;
    });

    User? user;
    Map<String, dynamic>? policy;
    List<Claim> claims = const <Claim>[];
    final loadIssues = <String>[];

    try {
      try {
        user = await _apiService.getProfile('me');
      } catch (_) {
        loadIssues.add('profile');
      }

      try {
        policy = await _apiService.getPolicy('me');
      } catch (_) {
        loadIssues.add('policy');
        policy = <String, dynamic>{};
      }

      try {
        claims = await _apiService.getClaims('me');
      } catch (_) {
        loadIssues.add('claims');
        claims = const <Claim>[];
      }

      if (!mounted) return;
      setState(() {
        _user = user ?? User.getMockUser();
        _policy = policy ?? <String, dynamic>{};
        _claims = claims;
      });

      if (loadIssues.isNotEmpty) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(
              loadIssues.length == 1
                  ? 'Failed to load ${loadIssues.first} from backend.'
                  : 'Loaded claims view with partial backend data.',
            ),
          ),
        );
      }
    } finally {
      if (mounted) {
        setState(() {
          _isLoadingClaims = false;
        });
      }
    }
  }

  Widget _buildTopUtilityButtons(User user) {
    final safeName = _coerceString(user.name, fallback: 'U');

    return Row(
      mainAxisAlignment: MainAxisAlignment.spaceBetween,
      children: [
        _utilityIconButton(
          icon: Icons.arrow_back,
          tooltip: 'Back to Home',
          onTap: () {
            _switchToTab(0);
          },
        ),
        Row(
          children: [
            _utilityIconButton(
              icon: Icons.notifications_none,
              tooltip: 'Notifications',
              onTap: () {
                _showNotificationsSheet();
              },
            ),
            const SizedBox(width: 10),
            Tooltip(
              message: 'Account',
              child: GestureDetector(
                onTap: () {
                  _showAccountSheet(user);
                },
                child: Container(
                  width: 42,
                  height: 42,
                  decoration: const BoxDecoration(
                    color: AppColors.primary,
                    shape: BoxShape.circle,
                  ),
                  child: Center(
                    child: Text(
                      _userInitials(safeName),
                      style: const TextStyle(
                        fontSize: 14,
                        fontWeight: FontWeight.w700,
                        color: Colors.white,
                      ),
                    ),
                  ),
                ),
              ),
            ),
          ],
        ),
      ],
    );
  }

  Widget _utilityIconButton({
    required IconData icon,
    required String tooltip,
    required VoidCallback onTap,
  }) {
    return Tooltip(
      message: tooltip,
      child: InkWell(
        borderRadius: BorderRadius.circular(12),
        onTap: onTap,
        child: Container(
          width: 42,
          height: 42,
          decoration: BoxDecoration(
            color: Colors.white.withValues(alpha: 0.2),
            borderRadius: BorderRadius.circular(12),
            border: Border.all(color: Colors.white.withValues(alpha: 0.28)),
          ),
          child: Icon(icon, size: 21, color: AppColors.textPrimary),
        ),
      ),
    );
  }

  List<Claim> get _filteredClaims {
    switch (_selectedTab) {
      case 1:
        return _claims
            .where((c) => c.status == ClaimStatus.inReview)
            .toList();
      case 2:
        return _claims
            .where((c) => c.status == ClaimStatus.settled)
            .toList();
      default:
        return _claims;
    }
  }

  @override
  Widget build(BuildContext context) {
    final user = _user;
    final weeklyPremium = (_policy?['weeklyPremium'] as num? ?? 0).toInt();
    final policyStatus = ((_policy?['status'] as String?) ?? 'active').toUpperCase();
    final inReviewCount = _claims.where((c) => c.status == ClaimStatus.inReview).length;

    if (_isLoadingClaims) {
      return const Scaffold(
        backgroundColor: AppColors.scaffoldBackground,
        body: Center(child: CircularProgressIndicator()),
      );
    }

    if (user == null) {
      return const Scaffold(
        backgroundColor: AppColors.scaffoldBackground,
        body: Center(
          child: Text(
            'Failed to load claims data.',
            style: TextStyle(color: AppColors.textSecondary),
          ),
        ),
      );
    }

    return Scaffold(
      backgroundColor: AppColors.scaffoldBackground,
      floatingActionButton: FloatingActionButton(
        onPressed: () {
          _showNewClaimSheet();
        },
        backgroundColor: AppColors.primary,
        child: const Icon(Icons.add, color: Colors.white),
      ),
      body: Stack(
        children: [
          const Positioned(
            top: 0,
            left: 0,
            right: 0,
            child: SizedBox(
              height: 205,
              child: CustomPaint(
                painter: _ClaimsTopBackgroundPainter(),
              ),
            ),
          ),
          SafeArea(
            child: SingleChildScrollView(
              padding: const EdgeInsets.symmetric(horizontal: 20),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const SizedBox(height: 16),

                  _buildTopUtilityButtons(user),
                  const SizedBox(height: 14),

                  // Header
                  const Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        'Claims',
                        style: TextStyle(
                          fontSize: 28,
                          fontWeight: FontWeight.w800,
                          color: AppColors.textPrimary,
                          letterSpacing: -0.4,
                        ),
                      ),
                      SizedBox(height: 4),
                      Text(
                        'Track status and settlements',
                        style: TextStyle(
                          fontSize: 13,
                          color: AppColors.textSecondary,
                        ),
                      ),
                    ],
                  ),
                  const SizedBox(height: 24),

              // Current protection header
              Container(
                width: double.infinity,
                padding: const EdgeInsets.all(20),
                decoration: BoxDecoration(
                  color: AppColors.primary,
                  borderRadius: BorderRadius.circular(20),
                ),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      'CURRENT PROTECTION',
                      style: TextStyle(
                        fontSize: 11,
                        fontWeight: FontWeight.w600,
                        color: Colors.white.withValues(alpha: 0.6),
                        letterSpacing: 1.2,
                      ),
                    ),
                    const SizedBox(height: 8),
                    Row(
                      mainAxisAlignment: MainAxisAlignment.spaceBetween,
                      children: [
                        Text(
                          '₹$weeklyPremium',
                          style: TextStyle(
                            fontSize: 36,
                            fontWeight: FontWeight.w800,
                            color: Colors.white,
                            letterSpacing: -0.5,
                          ),
                        ),
                        Container(
                          padding: const EdgeInsets.symmetric(
                              horizontal: 10, vertical: 5),
                          decoration: BoxDecoration(
                            color: AppColors.success,
                            borderRadius: BorderRadius.circular(8),
                          ),
                          child: Text(
                            policyStatus,
                            style: TextStyle(
                              fontSize: 10,
                              fontWeight: FontWeight.w700,
                              color: Colors.white,
                              letterSpacing: 0.8,
                            ),
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: 4),
                    Text(
                      '$inReviewCount pending settlements',
                      style: TextStyle(
                        fontSize: 13,
                        color: Colors.white.withValues(alpha: 0.6),
                      ),
                    ),
                  ],
                ),
              ),
              const SizedBox(height: 20),

              const Text(
                'Filter',
                style: TextStyle(
                  fontSize: 16,
                  fontWeight: FontWeight.w700,
                  color: AppColors.textPrimary,
                ),
              ),
              const SizedBox(height: 10),

              // Filter tabs
              Row(
                children: _tabs.asMap().entries.map((entry) {
                  final isSelected = _selectedTab == entry.key;
                  return Padding(
                    padding: const EdgeInsets.only(right: 8),
                    child: GestureDetector(
                      onTap: () {
                        setState(() {
                          _selectedTab = entry.key;
                        });
                      },
                      child: Container(
                        padding: const EdgeInsets.symmetric(
                            horizontal: 16, vertical: 10),
                        decoration: BoxDecoration(
                          color: isSelected
                              ? AppColors.primary
                              : AppColors.surfaceLight,
                          borderRadius: BorderRadius.circular(24),
                        ),
                        child: Text(
                          entry.value,
                          style: TextStyle(
                            fontSize: 13,
                            fontWeight: FontWeight.w600,
                            color: isSelected
                                ? Colors.white
                                : AppColors.textSecondary,
                          ),
                        ),
                      ),
                    ),
                  );
                }).toList(),
              ),
              const SizedBox(height: 20),

              const Text(
                'Recent Activity',
                style: TextStyle(
                  fontSize: 16,
                  fontWeight: FontWeight.w700,
                  color: AppColors.textPrimary,
                ),
              ),
              const SizedBox(height: 10),

              // Claims list
              if (_isLoadingClaims)
                const Padding(
                  padding: EdgeInsets.symmetric(vertical: 24),
                  child: Center(child: CircularProgressIndicator()),
                )
              else if (_filteredClaims.isEmpty)
                Center(
                  child: Padding(
                    padding: const EdgeInsets.symmetric(vertical: 40),
                    child: Column(
                      children: [
                        const Icon(
                          Icons.receipt_long_outlined,
                          size: 48,
                          color: AppColors.textTertiary,
                        ),
                        const SizedBox(height: 12),
                        const Text(
                          'No claims in this category',
                          style: TextStyle(
                            fontSize: 15,
                            color: AppColors.textSecondary,
                          ),
                        ),
                      ],
                    ),
                  ),
                ),
              for (final claim in _filteredClaims)
                Padding(
                  padding: const EdgeInsets.only(bottom: 12),
                  child: ClaimCard(
                    claim: claim,
                    onTap: () => _showClaimDetails(claim),
                  ),
                ),

              const SizedBox(height: 16),

              // Need help section
              Container(
                width: double.infinity,
                padding: const EdgeInsets.all(20),
                decoration: BoxDecoration(
                  color: AppColors.cardBackground,
                  borderRadius: BorderRadius.circular(20),
                  border: Border.all(color: AppColors.border),
                ),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Text(
                      'Need help with a claim?',
                      style: TextStyle(
                        fontSize: 16,
                        fontWeight: FontWeight.w600,
                        color: AppColors.textPrimary,
                      ),
                    ),
                    const SizedBox(height: 6),
                    Text(
                      'Our claim specialists are available 24/7 to assist you in Kannada, Hindi, and English.',
                      style: TextStyle(
                        fontSize: 13,
                        color: AppColors.textSecondary,
                        height: 1.4,
                      ),
                    ),
                  ],
                ),
              ),
              const SizedBox(height: 24),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }

  String _coerceString(Object? value, {String fallback = ''}) {
    if (value == null) return fallback;
    final text = value.toString().trim();
    return text.isEmpty ? fallback : text;
  }

  String _userInitials(String? name) {
    final safeName = _coerceString(name);
    final parts = safeName.trim().split(' ').where((p) => p.isNotEmpty).toList();
    if (parts.isEmpty) return 'U';
    if (parts.length == 1) return parts.first.substring(0, 1).toUpperCase();
    return '${parts.first[0]}${parts.last[0]}'.toUpperCase();
  }

  void _openProfile() {
    _switchToTab(4);
  }

  void _switchToTab(int index) {
    TabRouter.switchTo(index);
    Navigator.of(context).popUntil((route) => route.isFirst);
  }

  void _showNotificationsSheet() {
    showModalBottomSheet<void>(
      context: context,
      showDragHandle: true,
      builder: (_) {
        return ListView(
          shrinkWrap: true,
          padding: const EdgeInsets.fromLTRB(16, 8, 16, 20),
          children: const [
            ListTile(
              leading: Icon(Icons.update_outlined),
              title: Text('Claim #17210 moved to review'),
              subtitle: Text('Our team requested one additional proof image'),
            ),
            ListTile(
              leading: Icon(Icons.account_balance_wallet_outlined),
              title: Text('Settlement complete for #17209'),
              subtitle: Text('Rs 1,450 transferred to your linked bank'),
            ),
          ],
        );
      },
    );
  }

  void _showAccountSheet(User user) {
    final safeName = _coerceString(user.name, fallback: 'User');
    final safePhone = _coerceString(user.phone, fallback: 'No phone');

    showModalBottomSheet<void>(
      context: context,
      showDragHandle: true,
      builder: (sheetContext) {
        return SafeArea(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              ListTile(
                leading: CircleAvatar(
                  backgroundColor: AppColors.primary,
                  child: Text(
                    _userInitials(safeName),
                    style: const TextStyle(color: Colors.white, fontWeight: FontWeight.w700),
                  ),
                ),
                title: Text(safeName),
                subtitle: Text(safePhone),
                onTap: () {
                  Navigator.pop(sheetContext);
                  _openProfile();
                },
              ),
              ListTile(
                leading: const Icon(Icons.home_outlined),
                title: const Text('Home'),
                onTap: () {
                  Navigator.pop(sheetContext);
                  _switchToTab(0);
                },
              ),
              ListTile(
                leading: const Icon(Icons.receipt_long_outlined),
                title: const Text('Claims'),
                onTap: () {
                  Navigator.pop(sheetContext);
                  _switchToTab(1);
                },
              ),
              ListTile(
                leading: const Icon(Icons.shield_outlined),
                title: const Text('Coverage details'),
                onTap: () {
                  Navigator.pop(sheetContext);
                  _switchToTab(2);
                },
              ),
              ListTile(
                leading: const Icon(Icons.payments_outlined),
                title: const Text('Payouts'),
                onTap: () {
                  Navigator.pop(sheetContext);
                  _switchToTab(3);
                },
              ),
            ],
          ),
        );
      },
    );
  }

  Future<void> _showNewClaimSheet() async {
    String selectedType = 'TrafficBlock';
    final descriptionController = TextEditingController();

    try {
      await showModalBottomSheet<void>(
        context: context,
        isScrollControlled: true,
        showDragHandle: true,
        builder: (sheetContext) {
          return StatefulBuilder(
            builder: (sheetContext, setSheetState) {
              return Padding(
                padding: EdgeInsets.fromLTRB(
                  16,
                  8,
                  16,
                  math.max(0.0, MediaQuery.of(sheetContext).viewInsets.bottom) +
                      16,
                ),
                child: ConstrainedBox(
                  constraints: BoxConstraints(
                    maxHeight: MediaQuery.of(sheetContext).size.height * 0.85,
                  ),
                  child: SingleChildScrollView(
                    child: Column(
                      mainAxisSize: MainAxisSize.min,
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        const Text(
                          'Report a new claim',
                          style: TextStyle(fontSize: 20, fontWeight: FontWeight.w700),
                        ),
                        const SizedBox(height: 12),
                        const Text(
                          'Trigger type',
                          style: TextStyle(
                            fontSize: 14,
                            fontWeight: FontWeight.w600,
                            color: AppColors.textPrimary,
                          ),
                        ),
                        const SizedBox(height: 8),
                        Wrap(
                          spacing: 8,
                          runSpacing: 8,
                          children: [
                            'TrafficBlock',
                            'RainLock',
                            'AQI Guard',
                            'ZoneLock',
                            'HeatBlock',
                          ].map((type) {
                            final isSelected = selectedType == type;
                            return ChoiceChip(
                              label: Text(type),
                              selected: isSelected,
                              onSelected: (_) {
                                setSheetState(() {
                                  selectedType = type;
                                });
                              },
                            );
                          }).toList(),
                        ),
                        const SizedBox(height: 10),
                        TextField(
                          controller: descriptionController,
                          maxLines: 3,
                          decoration: const InputDecoration(
                            labelText: 'What happened?',
                            border: OutlineInputBorder(),
                          ),
                        ),
                        const SizedBox(height: 12),
                        SizedBox(
                          width: double.infinity,
                          child: ElevatedButton(
                            onPressed: () async {
                              final messenger = ScaffoldMessenger.of(context);
                              final navigator = Navigator.of(sheetContext);
                              final desc = descriptionController.text.trim().isEmpty
                                  ? 'No additional details provided'
                                  : descriptionController.text.trim();
                              ClaimType claimType = ClaimType.trafficBlock;
                              if (selectedType == 'RainLock') claimType = ClaimType.rainLock;
                              if (selectedType == 'AQI Guard') claimType = ClaimType.aqiGuard;
                              if (selectedType == 'ZoneLock') claimType = ClaimType.zoneLock;
                              if (selectedType == 'HeatBlock') claimType = ClaimType.heatBlock;

                              try {
                                await _apiService.submitClaim(
                                  userId: 'me',
                                  type: claimType,
                                  description: desc,
                                );
                                if (!context.mounted) return;
                                navigator.pop();
                                await _loadClaims();
                              } catch (_) {
                                if (!context.mounted) return;
                                messenger.showSnackBar(
                                  const SnackBar(
                                    content: Text('Claim submission failed. Please try again.'),
                                  ),
                                );
                                return;
                              }

                              if (!context.mounted) return;
                              messenger.showSnackBar(
                                SnackBar(
                                  content: Text(
                                    'Claim submitted: $selectedType · $desc',
                                  ),
                                ),
                              );
                            },
                            child: const Text('Submit claim'),
                          ),
                        ),
                      ],
                    ),
                  ),
                ),
              );
            },
          );
        },
      );
    } finally {
      descriptionController.dispose();
    }
  }

  void _showClaimDetails(Claim claim) {
    showModalBottomSheet<void>(
      context: context,
      showDragHandle: true,
      builder: (_) {
        return Padding(
          padding: const EdgeInsets.fromLTRB(16, 8, 16, 20),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                'Claim ${claim.id}',
                style: const TextStyle(fontSize: 20, fontWeight: FontWeight.w700),
              ),
              const SizedBox(height: 8),
              Text('Type: ${claim.typeShortName}'),
              Text('Status: ${claim.statusLabel}'),
              Text('Amount: Rs ${claim.amount.toStringAsFixed(0)}'),
              const SizedBox(height: 12),
              const Text(
                'Our reviewer will update this timeline as soon as verification completes.',
                style: TextStyle(color: AppColors.textSecondary),
              ),
            ],
          ),
        );
      },
    );
  }

  
}

class _ClaimsTopBackgroundPainter extends CustomPainter {
  const _ClaimsTopBackgroundPainter();

  @override
  void paint(Canvas canvas, Size size) {
    final backgroundPaint = Paint()
      ..shader = const LinearGradient(
        begin: Alignment.topCenter,
        end: Alignment.bottomCenter,
        colors: [
          Color(0xFFE7F2FF),
          Color(0xFFF0F8FF),
          Color(0xFFF8FBFF),
        ],
      ).createShader(Rect.fromLTWH(0, 0, size.width, size.height));

    canvas.drawRect(Rect.fromLTWH(0, 0, size.width, size.height), backgroundPaint);

    final shapePaint = Paint()..color = AppColors.info.withValues(alpha: 0.12);
    final shapePath = Path()
      ..moveTo(-20, size.height * 0.74)
      ..lineTo(size.width * 0.42, size.height * 0.56)
      ..lineTo(size.width + 30, size.height * 0.84)
      ..lineTo(size.width + 30, size.height)
      ..lineTo(-20, size.height)
      ..close();
    canvas.drawPath(shapePath, shapePaint);

    final ringPaint = Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = 1.5
      ..color = AppColors.info.withValues(alpha: 0.15);

    canvas.drawCircle(Offset(size.width * 0.18, size.height * 0.2), 32, ringPaint);
    canvas.drawCircle(Offset(size.width * 0.86, size.height * 0.3), 48, ringPaint);
  }

  @override
  bool shouldRepaint(covariant CustomPainter oldDelegate) => false;
}
