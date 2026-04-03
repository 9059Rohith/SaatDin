import 'package:flutter/material.dart';
import 'package:intl/intl.dart';

import '../../models/claim_model.dart';
import '../../models/plan_model.dart';
import '../../models/user_model.dart';
import '../../services/api_service.dart';
import '../../services/tab_router.dart';
import '../../theme/app_colors.dart';

class CoverageScreen extends StatefulWidget {
  const CoverageScreen({super.key});

  @override
  State<CoverageScreen> createState() => _CoverageScreenState();
}

class _CoverageScreenState extends State<CoverageScreen> {
  final ApiService _apiService = ApiService();
  List<InsurancePlan> _plans = const <InsurancePlan>[];
  List<Claim> _claims = const <Claim>[];
  User? _user;
  String? _pendingPlanName;
  String? _pendingEffectiveDate;
  bool _isLoading = true;
  int _currentTierIndex = 1;
  int _selectedTierIndex = 1;
  int _simulatorIndex = 1;

  final NumberFormat _currencyFormat = NumberFormat('#,##0');

  late final List<_TriggerInfo> _triggers = [
    const _TriggerInfo(
      title: 'RainLock',
      cause: 'Heavy rainfall in your registered pincode.',
      threshold: '> 35mm in 3 hours',
      payout: 400,
      lastTriggered: '12 days ago',
    ),
    const _TriggerInfo(
      title: 'AQI Guard',
      cause: 'Hazardous air quality sustained during shift window.',
      threshold: 'AQI > 250 for 4 hours',
      payout: 320,
      lastTriggered: '18 days ago',
    ),
    const _TriggerInfo(
      title: 'TrafficBlock',
      cause: 'Severe congestion blocks deliveries in your zone.',
      threshold: '< 5 kmph for 2 hours',
      payout: 280,
      lastTriggered: '6 days ago',
    ),
    const _TriggerInfo(
      title: 'ZoneLock',
      cause: 'Confirmed curfew, bandh, or civic shutdown in-zone.',
      threshold: 'Verified event in your pincode',
      payout: 400,
      lastTriggered: '27 days ago',
    ),
    const _TriggerInfo(
      title: 'HeatBlock',
      cause: 'Extreme heat and humidity make outdoor work unsafe.',
      threshold: '> 39 C and humidity > 70% for 4 hours',
      payout: 240,
      lastTriggered: '21 days ago',
    ),
  ];

  @override
  void initState() {
    super.initState();
    _loadCoverageData();
  }

  Future<void> _loadCoverageData() async {
    setState(() {
      _isLoading = true;
    });

    try {
      final user = await _apiService.getProfile('me');
      final policy = await _apiService.getPolicy('me');
      final plans = await _apiService.getPlans(zone: user.zone, platform: user.platform);
      final claims = await _apiService.getClaims('me');

      var currentIndex = plans.indexWhere(
        (p) => p.name.toLowerCase() == ((policy['plan'] as String? ?? user.plan).toLowerCase()),
      );
      if (currentIndex < 0) currentIndex = 0;

      if (!mounted) return;
      setState(() {
        _user = user;
        _plans = plans;
        _claims = claims;
        _pendingPlanName = policy['pendingPlan'] as String?;
        _pendingEffectiveDate = policy['pendingEffectiveDate'] as String?;
        _currentTierIndex = currentIndex;
        _selectedTierIndex = currentIndex;
        _simulatorIndex = currentIndex;
      });
    } catch (_) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Failed to load coverage from backend.')),
        );
      }
    } finally {
      if (mounted) {
        setState(() {
          _isLoading = false;
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    if (_isLoading) {
      return const Scaffold(
        backgroundColor: AppColors.scaffoldBackground,
        body: Center(child: CircularProgressIndicator()),
      );
    }

    final user = _user;
    if (user == null || _plans.isEmpty) {
      return const Scaffold(
        backgroundColor: AppColors.scaffoldBackground,
        body: Center(
          child: Text(
            'Coverage data unavailable. Please retry.',
            style: TextStyle(color: AppColors.textSecondary),
          ),
        ),
      );
    }

    final selectedPlan = _plans[_selectedTierIndex];
    final estimatedPremium = _calculateEstimatedPremium();

    return Scaffold(
      backgroundColor: AppColors.scaffoldBackground,
      body: Stack(
        children: [
          const Positioned(
            top: 0,
            left: 0,
            right: 0,
            child: SizedBox(
              height: 210,
              child: CustomPaint(
                painter: _CoverageTopBackgroundPainter(),
              ),
            ),
          ),
          SafeArea(
            child: SingleChildScrollView(
              padding: const EdgeInsets.fromLTRB(20, 16, 20, 28),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  _buildTopUtilityButtons(user),
                  const SizedBox(height: 14),
                  const Text(
                    'Coverage',
                    style: TextStyle(
                      fontSize: 30,
                      fontWeight: FontWeight.w800,
                      color: AppColors.textPrimary,
                      letterSpacing: -0.4,
                    ),
                  ),
                  const SizedBox(height: 6),
                  const Text(
                    'Understand what you pay for and manage policy week to week.',
                    style: TextStyle(
                      fontSize: 13,
                      color: AppColors.textSecondary,
                    ),
                  ),
                  const SizedBox(height: 18),
              const _CoverageSectionHeader('Tier Selector'),
              const SizedBox(height: 10),
              if (_pendingPlanName != null && _pendingPlanName!.isNotEmpty)
                Padding(
                  padding: const EdgeInsets.only(bottom: 10),
                  child: _buildPendingPlanNotice(),
                ),
              ..._plans.asMap().entries.map(
                (entry) {
                  final index = entry.key;
                  final plan = entry.value;
                  final isCurrent = index == _currentTierIndex;
                  final isSelected = index == _selectedTierIndex;

                  return Padding(
                    padding: const EdgeInsets.only(bottom: 10),
                    child: InkWell(
                      borderRadius: BorderRadius.circular(16),
                      onTap: () {
                        setState(() {
                          _selectedTierIndex = index;
                          _simulatorIndex = index;
                        });
                      },
                      child: Container(
                        width: double.infinity,
                        padding: const EdgeInsets.all(14),
                        decoration: BoxDecoration(
                          color: isSelected
                              ? AppColors.cardSelectedBackground
                              : AppColors.cardBackground,
                          borderRadius: BorderRadius.circular(16),
                          border: Border.all(
                            color: isSelected
                                ? AppColors.cardSelectedBorder
                                : AppColors.border,
                            width: isSelected ? 1.4 : 1,
                          ),
                        ),
                        child: Row(
                          children: [
                            Expanded(
                              child: Column(
                                crossAxisAlignment: CrossAxisAlignment.start,
                                children: [
                                  Row(
                                    children: [
                                      Text(
                                        plan.name,
                                        style: const TextStyle(
                                          fontSize: 17,
                                          fontWeight: FontWeight.w700,
                                          color: AppColors.textPrimary,
                                        ),
                                      ),
                                      if (isCurrent) ...[
                                        const SizedBox(width: 8),
                                        Container(
                                          padding: const EdgeInsets.symmetric(
                                            horizontal: 8,
                                            vertical: 3,
                                          ),
                                          decoration: BoxDecoration(
                                            color: AppColors.successLight,
                                            borderRadius: BorderRadius.circular(999),
                                          ),
                                          child: const Text(
                                            'Current',
                                            style: TextStyle(
                                              fontSize: 10,
                                              fontWeight: FontWeight.w700,
                                              color: AppColors.success,
                                            ),
                                          ),
                                        ),
                                      ],
                                    ],
                                  ),
                                  const SizedBox(height: 6),
                                  Text(
                                    'Est. weekly premium: Rs ${plan.weeklyPremium}',
                                    style: const TextStyle(
                                      fontSize: 13,
                                      color: AppColors.textSecondary,
                                    ),
                                  ),
                                  const SizedBox(height: 2),
                                  Text(
                                    'Per-trigger payout: Rs ${plan.perTriggerPayout}',
                                    style: const TextStyle(
                                      fontSize: 13,
                                      color: AppColors.textSecondary,
                                    ),
                                  ),
                                ],
                              ),
                            ),
                            Icon(
                              isSelected
                                  ? Icons.radio_button_checked
                                  : Icons.radio_button_off,
                              color: isSelected
                                  ? AppColors.primary
                                  : AppColors.textTertiary,
                            ),
                          ],
                        ),
                      ),
                    ),
                  );
                },
              ),
              const SizedBox(height: 2),
              SizedBox(
                width: double.infinity,
                child: ElevatedButton(
                  onPressed: _selectedTierIndex == _currentTierIndex
                      ? null
                      : () async {
                          try {
                            final policy = await _apiService.updatePolicyPlan(selectedPlan.name);
                            if (!context.mounted) return;
                            final pendingPlan = policy['pendingPlan'] as String?;
                            final pendingEffectiveDate = policy['pendingEffectiveDate'] as String?;
                            setState(() {
                              _pendingPlanName = pendingPlan;
                              _pendingEffectiveDate = pendingEffectiveDate;
                            });
                            ScaffoldMessenger.of(context).showSnackBar(
                              SnackBar(
                                content: Text(
                                  pendingEffectiveDate == null
                                      ? '${selectedPlan.name} plan will apply next week.'
                                      : '${selectedPlan.name} plan will apply from $pendingEffectiveDate.',
                                ),
                              ),
                            );
                          } catch (_) {
                            if (!context.mounted) return;
                            ScaffoldMessenger.of(context).showSnackBar(
                              const SnackBar(
                                content: Text('Policy update failed. Please verify login and retry.'),
                              ),
                            );
                          }
                        },
                  style: ElevatedButton.styleFrom(
                    backgroundColor: AppColors.primary,
                    foregroundColor: Colors.white,
                    disabledBackgroundColor: AppColors.border,
                    disabledForegroundColor: AppColors.textSecondary,
                    padding: const EdgeInsets.symmetric(vertical: 14),
                    shape: RoundedRectangleBorder(
                      borderRadius: BorderRadius.circular(14),
                    ),
                  ),
                  child: Text(
                    _selectedTierIndex == _currentTierIndex
                        ? 'Current tier active'
                        : 'Switch to ${selectedPlan.name}',
                    style: const TextStyle(fontWeight: FontWeight.w700),
                  ),
                ),
              ),
              const SizedBox(height: 20),
              const _CoverageSectionHeader('Premium Breakdown'),
              const SizedBox(height: 10),
              _buildCard(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    _breakdownRow('Base', 'Rs 45.00'),
                    const SizedBox(height: 8),
                    _breakdownRow('Zone risk (Bellandur 1.3x)', 'x 1.30'),
                    const SizedBox(height: 8),
                    _breakdownRow('Platform (Blinkit 1.1x)', 'x 1.10'),
                    const SizedBox(height: 8),
                    _breakdownRow(
                      'Loyalty discount (${_loyaltyDiscountPercent.toStringAsFixed(0)}%)',
                      '- ${_loyaltyDiscountPercent.toStringAsFixed(0)}%',
                    ),
                    const Padding(
                      padding: EdgeInsets.symmetric(vertical: 10),
                      child: Divider(height: 1, color: AppColors.border),
                    ),
                    _breakdownRow(
                      'Estimated weekly premium',
                      'Rs ${_currencyFormat.format(estimatedPremium)}',
                      emphasize: true,
                    ),
                  ],
                ),
              ),
              const SizedBox(height: 20),
              const _CoverageSectionHeader('Trigger Explainer'),
              const SizedBox(height: 10),
              _buildCard(
                child: Column(
                  children: _triggers
                      .map(
                        (trigger) => Theme(
                          data: Theme.of(context).copyWith(
                            dividerColor: Colors.transparent,
                          ),
                          child: ExpansionTile(
                            tilePadding: EdgeInsets.zero,
                            childrenPadding: const EdgeInsets.only(bottom: 12),
                            title: Text(
                              trigger.title,
                              style: const TextStyle(
                                fontSize: 15,
                                fontWeight: FontWeight.w700,
                                color: AppColors.textPrimary,
                              ),
                            ),
                            children: [
                              _triggerDetail('Cause', trigger.cause),
                              const SizedBox(height: 6),
                              _triggerDetail('Threshold', trigger.threshold),
                              const SizedBox(height: 6),
                              _triggerDetail(
                                'Payout',
                                'Rs ${_currencyFormat.format(trigger.payout)}',
                              ),
                              const SizedBox(height: 6),
                              _triggerDetail(
                                'Last triggered in your zone',
                                '${trigger.lastTriggered}, Rs ${_currencyFormat.format(trigger.payout)} paid',
                                accent: true,
                              ),
                            ],
                          ),
                        ),
                      )
                      .toList(),
                ),
              ),
              const SizedBox(height: 20),
              const _CoverageSectionHeader('Policy Document'),
              const SizedBox(height: 10),
              _buildCard(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Text(
                      'Covered: income loss due to verified RainLock, AQI Guard, TrafficBlock, ZoneLock, and HeatBlock events in your registered zone.',
                      style: TextStyle(
                        fontSize: 13,
                        color: AppColors.textSecondary,
                        height: 1.4,
                      ),
                    ),
                    const SizedBox(height: 8),
                    const Text(
                      'Not covered: health, life, personal injury, and vehicle repair costs.',
                      style: TextStyle(
                        fontSize: 13,
                        color: AppColors.textSecondary,
                        height: 1.4,
                      ),
                    ),
                    const SizedBox(height: 12),
                    OutlinedButton.icon(
                      onPressed: () {
                        ScaffoldMessenger.of(context).showSnackBar(
                          const SnackBar(
                            content: Text('Policy summary PDF download started.'),
                          ),
                        );
                      },
                      icon: const Icon(Icons.download_outlined, size: 18),
                      label: const Text('Download PDF Summary'),
                      style: OutlinedButton.styleFrom(
                        foregroundColor: AppColors.primary,
                        side: const BorderSide(color: AppColors.border),
                        padding: const EdgeInsets.symmetric(
                          horizontal: 14,
                          vertical: 10,
                        ),
                        shape: RoundedRectangleBorder(
                          borderRadius: BorderRadius.circular(12),
                        ),
                      ),
                    ),
                  ],
                ),
              ),
              const SizedBox(height: 20),
              const _CoverageSectionHeader('Loyalty Tracker'),
              const SizedBox(height: 10),
              _buildCard(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      _loyaltyHeadline,
                      style: const TextStyle(
                        fontSize: 14,
                        fontWeight: FontWeight.w700,
                        color: AppColors.textPrimary,
                      ),
                    ),
                    const SizedBox(height: 8),
                    ClipRRect(
                      borderRadius: BorderRadius.circular(999),
                      child: LinearProgressIndicator(
                        minHeight: 8,
                        value: _loyaltyProgress,
                        backgroundColor: AppColors.borderLight,
                        valueColor:
                            const AlwaysStoppedAnimation<Color>(AppColors.primary),
                      ),
                    ),
                    const SizedBox(height: 6),
                    Text(
                      _loyaltySubtext,
                      style: const TextStyle(
                        fontSize: 12,
                        color: AppColors.textSecondary,
                      ),
                    ),
                  ],
                ),
              ),
              const SizedBox(height: 20),
              const _CoverageSectionHeader('What-if Simulator'),
              const SizedBox(height: 10),
              _buildCard(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      'Selected tier: ${_plans[_simulatorIndex].name}',
                      style: const TextStyle(
                        fontSize: 14,
                        fontWeight: FontWeight.w700,
                        color: AppColors.textPrimary,
                      ),
                    ),
                    Slider(
                      value: _simulatorIndex.toDouble(),
                      min: 0,
                      max: (_plans.length - 1).toDouble(),
                      divisions: _plans.length > 1 ? _plans.length - 1 : null,
                      label: _plans[_simulatorIndex].name,
                      activeColor: AppColors.primary,
                      onChanged: (value) {
                        setState(() {
                          _simulatorIndex = value.round();
                        });
                      },
                    ),
                    Row(
                      mainAxisAlignment: MainAxisAlignment.spaceBetween,
                      children: _plans
                          .map(
                            (plan) => Text(
                              plan.name,
                              style: const TextStyle(
                                fontSize: 12,
                                color: AppColors.textSecondary,
                              ),
                            ),
                          )
                          .toList(),
                    ),
                    const SizedBox(height: 12),
                    Text(
                      'If you had been on ${_plans[_simulatorIndex].name} last month, your estimated payout would have been Rs ${_currencyFormat.format(_simulatedPayout(_simulatorIndex))}.',
                      style: const TextStyle(
                        fontSize: 13,
                        color: AppColors.textPrimary,
                        height: 1.4,
                      ),
                    ),
                  ],
                ),
              ),
                ],
              ),
            ),
          ),
        ],
      ),
    );
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

  double _calculateEstimatedPremium() {
    if (_plans.isEmpty) return 0;
    return _plans[_selectedTierIndex].weeklyPremium.toDouble();
  }

  int _simulatedPayout(int tierIndex) {
    switch (tierIndex) {
      case 0:
        return 760;
      case 1:
        return 1200;
      case 2:
        return 1650;
      default:
        return 0;
    }
  }

  Widget _buildPendingPlanNotice() {
    final safePendingDate = _coerceString(_pendingEffectiveDate);
    final effectiveText = safePendingDate.isEmpty
        ? 'next week'
        : DateFormat('d MMM').format(DateTime.tryParse(safePendingDate) ?? DateTime.now());
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
      decoration: BoxDecoration(
        color: AppColors.warning.withValues(alpha: 0.1),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: AppColors.warning.withValues(alpha: 0.35)),
      ),
      child: Text(
        'Pending change: $_pendingPlanName will become active on $effectiveText. Your current week coverage stays unchanged.',
        style: const TextStyle(
          fontSize: 12,
          color: AppColors.textPrimary,
          fontWeight: FontWeight.w600,
          height: 1.35,
        ),
      ),
    );
  }

  int get _cleanStreakWeeks {
    if (_claims.isEmpty) {
      return 6;
    }

    final now = DateTime.now();
    final today = DateTime(now.year, now.month, now.day);
    final claimDates = _claims
        .map((c) => DateTime(c.date.year, c.date.month, c.date.day))
        .toList();

    var streak = 0;
    for (var weekOffset = 0; weekOffset < 12; weekOffset++) {
      final weekStart = today.subtract(Duration(days: today.weekday - 1 + (weekOffset * 7)));
      final weekEnd = weekStart.add(const Duration(days: 7));
      final hasClaimThisWeek = claimDates.any(
        (date) => !date.isBefore(weekStart) && date.isBefore(weekEnd),
      );
      if (hasClaimThisWeek) {
        break;
      }
      streak++;
    }
    return streak;
  }

  double get _loyaltyDiscountPercent {
    if (_cleanStreakWeeks >= 6) return 10;
    if (_cleanStreakWeeks >= 4) return 5;
    return 0;
  }

  double get _loyaltyProgress {
    if (_loyaltyDiscountPercent >= 10) {
      return 1.0;
    }
    final targetWeeks = _loyaltyDiscountPercent >= 5 ? 6 : 4;
    return (_cleanStreakWeeks / targetWeeks).clamp(0, 1).toDouble();
  }

  String get _loyaltyHeadline {
    if (_loyaltyDiscountPercent >= 10) {
      return '$_cleanStreakWeeks-week clean streak - 10% discount applied';
    }
    if (_loyaltyDiscountPercent >= 5) {
      return '$_cleanStreakWeeks-week clean streak - 5% discount applied';
    }
    return '$_cleanStreakWeeks-week clean streak - no loyalty discount yet';
  }

  String get _loyaltySubtext {
    if (_loyaltyDiscountPercent >= 10) {
      return 'Maximum loyalty tier unlocked from backend claim history.';
    }
    final nextTarget = _loyaltyDiscountPercent >= 5 ? 6 : 4;
    final nextDiscount = _loyaltyDiscountPercent >= 5 ? 10 : 5;
    final remaining = (nextTarget - _cleanStreakWeeks).clamp(0, nextTarget);
    return '$remaining more clean weeks to unlock $nextDiscount% discount.';
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
              leading: Icon(Icons.notifications_active_outlined),
              title: Text('RainLock alert window active'),
              subtitle: Text('Heavy rain expected in your zone from 4-7 PM'),
            ),
            ListTile(
              leading: Icon(Icons.discount_outlined),
              title: Text('Loyalty streak updated'),
              subtitle: Text('Two more clean weeks unlock 10% discount'),
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

  Widget _buildCard({required Widget child}) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: AppColors.cardBackground,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: AppColors.border),
      ),
      child: child,
    );
  }

  Widget _breakdownRow(String label, String value, {bool emphasize = false}) {
    return Row(
      children: [
        Expanded(
          child: Text(
            label,
            style: TextStyle(
              fontSize: 13,
              fontWeight: emphasize ? FontWeight.w700 : FontWeight.w500,
              color: AppColors.textPrimary,
            ),
          ),
        ),
        Text(
          value,
          style: TextStyle(
            fontSize: 13,
            fontWeight: emphasize ? FontWeight.w800 : FontWeight.w600,
            color: AppColors.textPrimary,
          ),
        ),
      ],
    );
  }

  Widget _triggerDetail(String label, String value, {bool accent = false}) {
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        SizedBox(
          width: 130,
          child: Text(
            '$label:',
            style: const TextStyle(
              fontSize: 12,
              color: AppColors.textSecondary,
            ),
          ),
        ),
        Expanded(
          child: Text(
            value,
            style: TextStyle(
              fontSize: 12,
              color: accent ? AppColors.primary : AppColors.textPrimary,
              fontWeight: accent ? FontWeight.w600 : FontWeight.w500,
            ),
          ),
        ),
      ],
    );
  }
}

class _CoverageSectionHeader extends StatelessWidget {
  const _CoverageSectionHeader(this.title);

  final String title;

  @override
  Widget build(BuildContext context) {
    return Text(
      title,
      style: const TextStyle(
        fontSize: 16,
        fontWeight: FontWeight.w700,
        color: AppColors.textPrimary,
      ),
    );
  }
}

class _TriggerInfo {
  const _TriggerInfo({
    required this.title,
    required this.cause,
    required this.threshold,
    required this.payout,
    required this.lastTriggered,
  });

  final String title;
  final String cause;
  final String threshold;
  final int payout;
  final String lastTriggered;
}

class _CoverageTopBackgroundPainter extends CustomPainter {
  const _CoverageTopBackgroundPainter();

  @override
  void paint(Canvas canvas, Size size) {
    final base = Paint()
      ..shader = const LinearGradient(
        begin: Alignment.topLeft,
        end: Alignment.bottomRight,
        colors: [
          AppColors.accentLight,
          Color(0xFFD7F3EF),
          Color(0xFFF4FBF9),
        ],
      ).createShader(Rect.fromLTWH(0, 0, size.width, size.height));

    final basePath = Path()
      ..moveTo(0, 0)
      ..lineTo(size.width, 0)
      ..lineTo(size.width, size.height * 0.86)
      ..lineTo(size.width * 0.68, size.height * 0.78)
      ..lineTo(size.width * 0.32, size.height * 0.94)
      ..lineTo(0, size.height * 0.82)
      ..close();

    canvas.drawPath(basePath, base);

    final stripePaint = Paint()
      ..color = AppColors.primary.withValues(alpha: 0.08)
      ..style = PaintingStyle.stroke
      ..strokeWidth = 1.2;

    canvas.drawLine(
      Offset(size.width * 0.08, size.height * 0.22),
      Offset(size.width * 0.92, size.height * 0.42),
      stripePaint,
    );
    canvas.drawLine(
      Offset(size.width * 0.02, size.height * 0.38),
      Offset(size.width * 0.74, size.height * 0.64),
      stripePaint,
    );

    final dotPaint = Paint()..color = AppColors.accent.withValues(alpha: 0.18);
    canvas.drawCircle(Offset(size.width * 0.15, size.height * 0.12), 12, dotPaint);
    canvas.drawCircle(Offset(size.width * 0.82, size.height * 0.2), 20, dotPaint);
    canvas.drawCircle(Offset(size.width * 0.58, size.height * 0.72), 10, dotPaint);
  }

  @override
  bool shouldRepaint(covariant CustomPainter oldDelegate) => false;
}
