import 'package:flutter/material.dart';
import 'package:intl/intl.dart';
import '../../theme/app_colors.dart';
import '../../models/user_model.dart';
import '../../models/claim_model.dart';
import '../../models/plan_model.dart';
import '../../routes/app_routes.dart';
import '../../services/api_service.dart';
import '../../services/tab_router.dart';

class HomeScreen extends StatelessWidget {
  const HomeScreen({super.key});

  static final ApiService _apiService = ApiService();

  Future<_HomeViewData> _loadHomeViewData() async {
    final user = await _apiService.getProfile('me');
    final policy = await _apiService.getPolicy('me');
    final claims = await _apiService.getClaims('me');
    final latestClaim = _latestClaimForUpdates(claims);
    final perTriggerPayout = (policy['perTriggerPayout'] as num? ?? 0).toDouble();
    final zoneKey = (policy['zonePincode'] as String? ?? user.zonePincode).trim();

    final maxDaysPerWeek = (policy['maxDaysPerWeek'] as num? ?? 0).toInt();
    final nextBillingRaw = (policy['nextBillingDate'] as String? ?? '').trim();
    final nextBillingDate = DateTime.tryParse(nextBillingRaw);
    final serverNow = nextBillingDate != null
        ? nextBillingDate.toUtc().subtract(const Duration(days: 7))
        : DateTime.now().toUtc();
    final weekStart = serverNow.subtract(Duration(days: serverNow.weekday - 1));
    final weekEnd = weekStart.add(const Duration(days: 7));

    final claimsThisWeek = claims.where((claim) {
      final claimDate = claim.date.toUtc();
      return !claimDate.isBefore(weekStart) && claimDate.isBefore(weekEnd);
    }).toList();

    final claimsProcessedThisWeek = claimsThisWeek.length;
    final payoutThisWeek = claimsThisWeek
        .where((claim) => claim.status == ClaimStatus.settled)
        .fold<double>(0, (sum, claim) => sum + claim.amount);
    final settledAutoTriggersThisWeek = claimsThisWeek
        .where((claim) => claim.status == ClaimStatus.settled)
        .toList()
      ..sort((left, right) => right.date.compareTo(left.date));
    final autoTriggerMessages = <String>[];

    if (claims.isNotEmpty) {
      try {
        final activeTrigger = await _apiService.getActiveTriggers(
          zoneKey.isNotEmpty ? zoneKey : user.zone,
        );
        if (activeTrigger['hasActiveAlert'] == true) {
          autoTriggerMessages.add(
            _buildLiveTriggerImpactMessage(activeTrigger, perTriggerPayout),
          );
        }
      } catch (_) {
        // Fall back to claims-based updates if trigger endpoint fails.
      }
    }

    if (settledAutoTriggersThisWeek.isNotEmpty) {
      autoTriggerMessages.add(
        _buildTriggerImpactMessage(settledAutoTriggersThisWeek.first),
      );
    }

    final daysUntilBilling = nextBillingDate != null
        ? nextBillingDate.toUtc().difference(serverNow).inDays.clamp(0, 7)
        : 7;
    final coveredDaysLeft = (maxDaysPerWeek - claimsProcessedThisWeek)
        .clamp(0, maxDaysPerWeek)
        .clamp(0, daysUntilBilling);

    final activePlan = InsurancePlan(
      name: (policy['plan'] as String? ?? user.plan).trim(),
      weeklyPremium: (policy['weeklyPremium'] as num? ?? 0).toInt(),
      perTriggerPayout: (policy['perTriggerPayout'] as num? ?? 0).toInt(),
      maxDaysPerWeek: (policy['maxDaysPerWeek'] as num? ?? 0).toInt(),
      isPopular: false,
    );

    return _HomeViewData(
      user: user,
      claims: claims,
      latestClaim: latestClaim,
      autoTriggerMessages: autoTriggerMessages,
      activePlan: activePlan,
      earningsProtected: (policy['earningsProtected'] as num? ?? 0).toDouble(),
      totalEarnings: user.totalEarnings > 0
          ? user.totalEarnings
          : claims
              .where((claim) => claim.status == ClaimStatus.settled)
              .fold<double>(0, (sum, claim) => sum + claim.amount),
      coveredDaysLeft: coveredDaysLeft,
      claimsProcessedThisWeek: claimsProcessedThisWeek,
      payoutThisWeek: payoutThisWeek,
    );
  }

  Claim? _latestClaimForUpdates(List<Claim> claims) {
    final nonReviewClaims = claims
        .where((claim) => claim.status != ClaimStatus.inReview)
        .toList()
      ..sort((left, right) => right.date.compareTo(left.date));

    if (nonReviewClaims.isNotEmpty) {
      return nonReviewClaims.first;
    }

    final allClaims = claims.toList()
      ..sort((left, right) => right.date.compareTo(left.date));
    return allClaims.isNotEmpty ? allClaims.first : null;
  }

  String _buildTriggerImpactMessage(Claim claim) {
    final amount = NumberFormat('#,##0').format(claim.amount);
    switch (claim.type) {
      case ClaimType.rainLock:
        return 'Congratulations! Your rain cover has been settled. Hurray, ₹$amount has been credited to your account.';
      case ClaimType.trafficBlock:
        return 'Congratulations! Your traffic cover has been settled. Hurray, ₹$amount has been credited to your account.';
      case ClaimType.zoneLock:
        return 'Congratulations! Your zone lock cover has been settled. Hurray, ₹$amount has been credited to your account.';
      case ClaimType.aqiGuard:
        return 'Congratulations! Your AQI cover has been settled. Hurray, ₹$amount has been credited to your account.';
      case ClaimType.heatBlock:
        return 'Congratulations! Your heat cover has been settled. Hurray, ₹$amount has been credited to your account.';
    }
  }

  String _buildLiveTriggerImpactMessage(
    Map<String, dynamic> trigger,
    double perTriggerPayout,
  ) {
    final triggerType = (trigger['alertType'] as String? ?? 'none').toLowerCase();
    final amount = NumberFormat('#,##0').format(perTriggerPayout);

    switch (triggerType) {
      case 'rain':
        return 'Hurray! Rain has been noticed in your area today. Your cover is active, and ₹$amount will be settled into your account.';
      case 'traffic':
        return 'Hurray! Traffic has picked up in your area today. Your cover is active, and ₹$amount will be settled into your account.';
      case 'zonelock':
        return 'Hurray! A zone lock is active in your area today. Your cover is active, and ₹$amount will be settled into your account.';
      case 'aqi':
        return 'Hurray! The air quality in your area needs attention today. Your cover is active, and ₹$amount will be settled into your account.';
      case 'heat':
        return 'Hurray! It is a very hot day in your area. Your cover is active, and ₹$amount will be settled into your account.';
      default:
        return 'Hurray! We noticed something in your area today. Your cover is active, and it will be settled into your account.';
    }
  }

  // Returns the icon and background colour for a trigger message based on its type.
  ({IconData icon, Color background, Color iconColor}) _triggerIconData(String message) {
    final lower = message.toLowerCase();
    if (lower.contains('rain')) {
      return (
        icon: Icons.water_drop_outlined,
        background: const Color(0xFFE6F1FB),
        iconColor: const Color(0xFF185FA5),
      );
    } else if (lower.contains('traffic')) {
      return (
        icon: Icons.traffic_outlined,
        background: const Color(0xFFFAEEDA),
        iconColor: const Color(0xFFBA7517),
      );
    } else if (lower.contains('zone')) {
      return (
        icon: Icons.location_off_outlined,
        background: const Color(0xFFFBEAF0),
        iconColor: const Color(0xFF993556),
      );
    } else if (lower.contains('aqi') || lower.contains('air')) {
      return (
        icon: Icons.air_outlined,
        background: const Color(0xFFEAF3DE),
        iconColor: const Color(0xFF3B6D11),
      );
    } else if (lower.contains('heat') || lower.contains('hot')) {
      return (
        icon: Icons.thermostat_outlined,
        background: const Color(0xFFFCEBEB),
        iconColor: const Color(0xFFA32D2D),
      );
    }
    return (
      icon: Icons.bolt_rounded,
      background: const Color(0xFFE1F5EE),
      iconColor: AppColors.primary,
    );
  }

  // Returns a short human-readable title for a trigger message.
  String _triggerTitle(String message) {
    final lower = message.toLowerCase();
    if (lower.contains('rain')) return 'Rain payout incoming';
    if (lower.contains('traffic')) return 'Traffic payout incoming';
    if (lower.contains('zone')) return 'Zone lock payout incoming';
    if (lower.contains('aqi') || lower.contains('air')) return 'AQI payout incoming';
    if (lower.contains('heat') || lower.contains('hot')) return 'Heat payout incoming';
    return 'Payout incoming';
  }

  InlineSpan _buildAmountHighlightedSpan(String message, TextStyle baseStyle) {
    final amountPattern = RegExp(r'₹[\d,]+(?:\.\d+)?');
    final match = amountPattern.firstMatch(message);

    if (match == null) {
      return TextSpan(text: message, style: baseStyle);
    }

    return TextSpan(
      style: baseStyle,
      children: [
        if (match.start > 0) TextSpan(text: message.substring(0, match.start)),
        TextSpan(
          text: match.group(0),
          style: baseStyle.copyWith(
            fontWeight: FontWeight.w700,
            color: AppColors.primary,
          ),
        ),
        if (match.end < message.length) TextSpan(text: message.substring(match.end)),
      ],
    );
  }

  @override
  Widget build(BuildContext context) {
    return FutureBuilder<_HomeViewData>(
      future: _loadHomeViewData(),
      builder: (context, snapshot) {
        if (snapshot.connectionState == ConnectionState.waiting) {
          return const Scaffold(
            backgroundColor: AppColors.scaffoldBackground,
            body: Center(child: CircularProgressIndicator()),
          );
        }

        if (snapshot.hasError || snapshot.data == null) {
          return const Scaffold(
            backgroundColor: AppColors.scaffoldBackground,
            body: Center(
              child: Text(
                'Failed to load home data. Please retry.',
                style: TextStyle(color: AppColors.textSecondary),
              ),
            ),
          );
        }

        return _buildWithData(context, snapshot.data!);
      },
    );
  }

  Widget _buildWithData(BuildContext context, _HomeViewData data) {
    final user = data.user;
    final activePlan = data.activePlan;
    final cycleStart = DateTime.now();
    final cycleEnd = cycleStart.add(const Duration(days: 7));

    return Scaffold(
      backgroundColor: AppColors.background,
      body: SafeArea(
        top: false,
        child: Stack(
          children: [
            const Positioned(
              top: 0,
              left: 0,
              right: 0,
              child: SizedBox(
                height: 210,
                child: CustomPaint(
                  painter: _HomeTopBackgroundPainter(topHeight: 210),
                ),
              ),
            ),
            SingleChildScrollView(
              padding: const EdgeInsets.fromLTRB(20, 48, 20, 28),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  _buildTopHeader(context, user, data.autoTriggerMessages),
                  const SizedBox(height: 14),
                  Container(
                    width: double.infinity,
                    height: 1,
                    color: AppColors.border,
                  ),
                  const SizedBox(height: 16),
                  _buildPolicyOverviewCard(
                    context,
                    user,
                    activePlan,
                    cycleStart,
                    cycleEnd,
                  ),
                  const SizedBox(height: 14),
                  _buildTodaysUpdatesSnapshot(data.latestClaim),
                  const SizedBox(height: 24),
                  const Text(
                    'Quick access',
                    style: TextStyle(
                      fontSize: 24,
                      fontWeight: FontWeight.w800,
                      color: AppColors.textPrimary,
                      letterSpacing: -0.4,
                    ),
                  ),
                  const SizedBox(height: 10),
                  _buildQuickActions(context),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildFixedTopLayer(
    BuildContext context,
    User user,
    InsurancePlan activePlan,
    DateTime cycleStart,
    DateTime cycleEnd,
  ) {
    return SafeArea(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(20, 14, 20, 0),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            _buildTopHeader(context, user, const <String>[]),
            const SizedBox(height: 16),
            _buildPolicyOverviewCard(
              context,
              user,
              activePlan,
              cycleStart,
              cycleEnd,
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildScrollableLowerLayer(
    BuildContext context,
    double scrollStart,
    User user,
    List<Claim> claims,
    List<String> autoTriggerMessages,
    NumberFormat currencyFormat,
    DateFormat dateFormat,
    InsurancePlan activePlan,
    double earningsProtected,
    double? totalEarnings,
    int coveredDaysLeft,
    int claimsProcessedThisWeek,
    double payoutThisWeek,
  ) {
    return Positioned.fill(
      top: scrollStart,
      child: Container(
        decoration: const BoxDecoration(
          color: AppColors.scaffoldBackground,
          borderRadius: BorderRadius.vertical(top: Radius.circular(24)),
        ),
        child: SingleChildScrollView(
          padding: const EdgeInsets.fromLTRB(20, 32, 20, 28),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
                _buildTodaysUpdatesSnapshot(_latestClaimForUpdates(claims)),
              const SizedBox(height: 18),
              _buildMetricsRow(
                user,
                currencyFormat,
                earningsProtected: earningsProtected,
                totalEarnings: totalEarnings,
              ),
              const SizedBox(height: 18),
              _buildSectionHeader('Quick access'),
              const SizedBox(height: 10),
              _buildQuickActions(context),
              const SizedBox(height: 18),
              _buildSectionHeader('This Week'),
              const SizedBox(height: 10),
              _buildWeeklySnapshot(
                currencyFormat,
                coveredDaysLeft: coveredDaysLeft,
                claimsProcessedThisWeek: claimsProcessedThisWeek,
                payoutThisWeek: payoutThisWeek,
              ),
              const SizedBox(height: 18),
              _buildSectionHeader(
                'Recent Claims',
                actionText: 'View all',
                onTap: () {
                  _openClaims(context);
                },
              ),
              const SizedBox(height: 10),
              _buildRecentClaims(claims, currencyFormat, dateFormat),
              const SizedBox(height: 18),
              _buildSectionHeader('Next Billing'),
              const SizedBox(height: 10),
              _buildNextBillingCard(context, activePlan),
              const SizedBox(height: 16),
              _buildPrimaryActions(context),
            ],
          ),
        ),
      ),
    );
  }

  // ─── Top header ───────────────────────────────────────────────────────────

  Widget _buildTopHeader(
    BuildContext context,
    User user,
    List<String> recentTriggers,
  ) {
    final firstName =
        user.name.trim().isEmpty ? 'Rider' : user.name.split(' ').first;
    final initials = _userInitials(user.name);
    final hasNotifications = recentTriggers.isNotEmpty;

    return Row(
      crossAxisAlignment: CrossAxisAlignment.center,
      children: [
        // Avatar with initials – tapping opens account menu.
        GestureDetector(
          onTap: () => _showAccountQuickMenu(context),
          child: Container(
            width: 40,
            height: 40,
            decoration: BoxDecoration(
              color: AppColors.primary,
              shape: BoxShape.circle,
            ),
            child: Center(
              child: Text(
                initials,
                style: const TextStyle(
                  fontSize: 14,
                  fontWeight: FontWeight.w700,
                  color: Colors.white,
                  letterSpacing: 0.4,
                ),
              ),
            ),
          ),
        ),
        const SizedBox(width: 12),
        // Two-line greeting.
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                _greetingLabel(),
                style: const TextStyle(
                  fontSize: 12,
                  fontWeight: FontWeight.w600,
                  color: AppColors.textSecondary,
                  letterSpacing: 0.5,
                ),
              ),
              const SizedBox(height: 1),
              Text(
                'Hi, $firstName 👋',
                style: const TextStyle(
                  fontSize: 20,
                  fontWeight: FontWeight.w900,
                  color: AppColors.textPrimary,
                  letterSpacing: -0.4,
                  height: 1.1,
                ),
              ),
            ],
          ),
        ),
        // Bell icon with optional notification dot.
        GestureDetector(
          onTap: () => _showRecentTriggersSheet(context, recentTriggers),
          child: Container(
            width: 40,
            height: 40,
            decoration: BoxDecoration(
              color: Colors.white,
              shape: BoxShape.circle,
              border: Border.all(color: AppColors.border),
            ),
            child: Stack(
              alignment: Alignment.center,
              children: [
                const Icon(
                  Icons.notifications_none_rounded,
                  size: 20,
                  color: AppColors.textPrimary,
                ),
                if (hasNotifications)
                  Positioned(
                    top: 9,
                    right: 9,
                    child: Container(
                      width: 7,
                      height: 7,
                      decoration: BoxDecoration(
                        color: const Color(0xFFE24B4A),
                        shape: BoxShape.circle,
                        border: Border.all(color: Colors.white, width: 1.5),
                      ),
                    ),
                  ),
              ],
            ),
          ),
        ),
      ],
    );
  }

  String _userInitials(String name) {
    final parts = name.trim().split(' ').where((p) => p.isNotEmpty).toList();
    if (parts.isEmpty) return '?';
    if (parts.length == 1) return parts.first.substring(0, 1).toUpperCase();
    return '${parts.first[0]}${parts.last[0]}'.toUpperCase();
  }

  String _greetingLabel() {
    final hour = DateTime.now().hour;
    if (hour < 12) return 'Good morning';
    if (hour < 17) return 'Good afternoon';
    return 'Good evening';
  }

  void _showAccountQuickMenu(BuildContext context) {
    showModalBottomSheet<void>(
      context: context,
      showDragHandle: true,
      builder: (sheetContext) {
        return SafeArea(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              ListTile(
                leading: const Icon(Icons.settings_outlined),
                title: const Text('Settings'),
                onTap: () {
                  Navigator.pop(sheetContext);
                  ScaffoldMessenger.of(context).showSnackBar(
                    const SnackBar(content: Text('Settings screen coming soon.')),
                  );
                },
              ),
              ListTile(
                leading: const Icon(Icons.logout),
                title: const Text('Logout'),
                onTap: () {
                  Navigator.pop(sheetContext);
                  Navigator.pushNamedAndRemoveUntil(
                    context,
                    AppRoutes.welcome,
                    (route) => false,
                  );
                },
              ),
            ],
          ),
        );
      },
    );
  }

  void _showRecentTriggersSheet(BuildContext context, List<String> recentTriggers) {
    showModalBottomSheet<void>(
      context: context,
      showDragHandle: true,
      builder: (sheetContext) {
        return ListView(
          shrinkWrap: true,
          padding: const EdgeInsets.fromLTRB(16, 8, 16, 20),
          children: [
            const Text(
              'Recent triggers',
              style: TextStyle(fontSize: 18, fontWeight: FontWeight.w700),
            ),
            const SizedBox(height: 10),
            if (recentTriggers.isEmpty)
              const ListTile(
                contentPadding: EdgeInsets.zero,
                leading: Icon(Icons.info_outline),
                title: Text('No trigger alerts yet'),
                subtitle: Text('You will see new trigger events here.'),
              )
            else
              ...recentTriggers.map(
                (trigger) => ListTile(
                  contentPadding: EdgeInsets.zero,
                  leading:
                      const Icon(Icons.bolt_rounded, color: AppColors.primary),
                  title: Text(trigger),
                ),
              ),
          ],
        );
      },
    );
  }

  // ─── Policy overview card ─────────────────────────────────────────────────

  Widget _buildPolicyOverviewCard(
    BuildContext context,
    User user,
    InsurancePlan activePlan,
    DateTime cycleStart,
    DateTime cycleEnd,
  ) {
    final dateRange =
        '${DateFormat('MMM d').format(cycleStart)} → ${DateFormat('MMM d, y').format(cycleEnd)}';
    final planTitle =
        activePlan.name.trim().isEmpty ? 'Standard' : activePlan.name.trim();
    final zonePincode = user.zonePincode.trim();
    final platformZone = zonePincode.isEmpty
      ? '${user.platform} · ${user.zone}'
      : '${user.platform} · ${user.zone} · $zonePincode';

    return Container(
      width: double.infinity,
      padding: const EdgeInsets.fromLTRB(20, 18, 20, 18),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(20),
        gradient: const LinearGradient(
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
          colors: [
            Color(0xFF1BAA80),
            Color(0xFF0E6E56),
            Color(0xFF09503E),
          ],
        ),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // "Active" badge – top right with a pulsing green dot.
          Align(
            alignment: Alignment.centerRight,
            child: Container(
              padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
              decoration: BoxDecoration(
                color: Colors.white.withValues(alpha: 0.18),
                borderRadius: BorderRadius.circular(999),
                border: Border.all(
                  color: Colors.white.withValues(alpha: 0.32),
                ),
              ),
              child: Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Container(
                    width: 6,
                    height: 6,
                    decoration: const BoxDecoration(
                      color: Color(0xFF6EFFC2),
                      shape: BoxShape.circle,
                    ),
                  ),
                  const SizedBox(width: 5),
                  const Text(
                    'Active',
                    style: TextStyle(
                      fontSize: 12,
                      fontWeight: FontWeight.w600,
                      color: Colors.white,
                      letterSpacing: 0.3,
                    ),
                  ),
                ],
              ),
            ),
          ),
          const SizedBox(height: 6),
          Text(
            'Current plan',
            style: TextStyle(
              fontSize: 12,
              fontWeight: FontWeight.w600,
              color: Colors.white.withValues(alpha: 0.7),
              letterSpacing: 0.5,
            ),
          ),
          const SizedBox(height: 4),
          Text(
            '$planTitle',
            style: const TextStyle(
              fontSize: 42,
              fontWeight: FontWeight.w800,
              color: Colors.white,
              letterSpacing: -1.0,
              height: 1.0,
            ),
          ),
          const SizedBox(height: 14),
          // Date and zone on a single row separated by a vertical divider.
          Row(
            children: [
              Icon(
                Icons.calendar_today_outlined,
                size: 14,
                color: Colors.white.withValues(alpha: 0.75),
              ),
              const SizedBox(width: 5),
              Text(
                dateRange,
                style: TextStyle(
                  fontSize: 13,
                  color: Colors.white.withValues(alpha: 0.85),
                  fontWeight: FontWeight.w500,
                ),
              ),
              const SizedBox(width: 10),
              Container(
                width: 1,
                height: 12,
                color: Colors.white.withValues(alpha: 0.3),
              ),
              const SizedBox(width: 10),
              Icon(
                Icons.wb_sunny_outlined,
                size: 14,
                color: Colors.white.withValues(alpha: 0.75),
              ),
              const SizedBox(width: 5),
              Flexible(
                child: Text(
                  platformZone,
                  overflow: TextOverflow.ellipsis,
                  style: TextStyle(
                    fontSize: 13,
                    color: Colors.white.withValues(alpha: 0.85),
                    fontWeight: FontWeight.w600,
                  ),
                ),
              ),
            ],
          ),
          const SizedBox(height: 18),
          // Buttons – ghost "View Details" and solid white "File a Claim".
          Row(
            children: [
              Expanded(
                child: SizedBox(
                  height: 46,
                  child: OutlinedButton.icon(
                    onPressed: () => _openCoverage(context),
                    icon: const Icon(Icons.description_outlined, size: 16),
                    label: const Text('View Details'),
                    style: OutlinedButton.styleFrom(
                      foregroundColor: Colors.white,
                      side: BorderSide(
                        color: Colors.white.withValues(alpha: 0.4),
                      ),
                      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 0),
                      minimumSize: const Size(0, 44),
                      tapTargetSize: MaterialTapTargetSize.shrinkWrap,
                      shape: RoundedRectangleBorder(
                        borderRadius: BorderRadius.circular(12),
                      ),
                      textStyle: const TextStyle(
                        fontSize: 14,
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                  ),
                ),
              ),
              const SizedBox(width: 10),
              Expanded(
                child: SizedBox(
                  height: 46,
                  child: ElevatedButton.icon(
                    onPressed: () => _showQuickClaimSheet(context),
                    icon: const Icon(Icons.add, size: 16),
                    label: const Text('File a Claim'),
                    style: ElevatedButton.styleFrom(
                      backgroundColor: Colors.white,
                      foregroundColor: const Color(0xFF0E6E56),
                      elevation: 0,
                      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 0),
                      minimumSize: const Size(0, 44),
                      tapTargetSize: MaterialTapTargetSize.shrinkWrap,
                      shape: RoundedRectangleBorder(
                        borderRadius: BorderRadius.circular(12),
                      ),
                      textStyle: const TextStyle(
                        fontSize: 14,
                        fontWeight: FontWeight.w700,
                      ),
                    ),
                  ),
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }

  // ─── Today's updates ──────────────────────────────────────────────────────

  Widget _buildTodaysUpdatesSnapshot(Claim? latestClaim) {
    final hasUpdates = latestClaim != null;
    final claim = latestClaim;

    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: AppColors.cardBackground,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: AppColors.border),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text(
            "Today's updates",
            style: TextStyle(
              fontSize: 16,
              fontWeight: FontWeight.w800,
              color: AppColors.textPrimary,
            ),
          ),
          const SizedBox(height: 2),
          const Text(
            'Latest claim activity for your account',
            style: TextStyle(
              fontSize: 12,
              fontWeight: FontWeight.w500,
              color: AppColors.textSecondary,
            ),
          ),
          const SizedBox(height: 12),
          if (!hasUpdates)
            Row(
              children: [
                Container(
                  width: 32,
                  height: 32,
                  decoration: BoxDecoration(
                    color: const Color(0xFFEAF3DE),
                    borderRadius: BorderRadius.circular(8),
                  ),
                  child: const Icon(
                    Icons.verified_outlined,
                    size: 16,
                    color: Color(0xFF3B6D11),
                  ),
                ),
                const SizedBox(width: 10),
                const Expanded(
                  child: Text(
                    'No claims found yet. Your latest claim will show here.',
                    style: TextStyle(
                      fontSize: 13,
                      fontWeight: FontWeight.w600,
                      color: AppColors.success,
                      height: 1.4,
                    ),
                  ),
                ),
              ],
            )
          else if (claim != null)
            Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Container(
                  width: 32,
                  height: 32,
                  decoration: BoxDecoration(
                    color: claim.typeColor.withValues(alpha: 0.14),
                    borderRadius: BorderRadius.circular(8),
                  ),
                  child: Icon(
                    claim.typeIcon,
                    size: 16,
                    color: claim.typeColor,
                  ),
                ),
                const SizedBox(width: 10),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        '${claim.typeShortName} · ${claim.id}',
                        style: const TextStyle(
                          fontSize: 13,
                          fontWeight: FontWeight.w700,
                          color: AppColors.textPrimary,
                        ),
                      ),
                      const SizedBox(height: 2),
                      Text(
                        '${DateFormat('EEE, d MMM').format(claim.date)} · ${claim.statusLabel}',
                        style: const TextStyle(
                          fontSize: 12,
                          fontWeight: FontWeight.w500,
                          color: AppColors.textSecondary,
                        ),
                      ),
                      const SizedBox(height: 4),
                      Text(
                        '₹${NumberFormat('#,##0').format(claim.amount)} credited for ${claim.typeName.toLowerCase()}.',
                        style: const TextStyle(
                          fontSize: 13,
                          fontWeight: FontWeight.w500,
                          color: AppColors.textSecondary,
                          height: 1.4,
                        ),
                      ),
                    ],
                  ),
                ),
              ],
            ),
        ],
      ),
    );
  }

  // ─── Quick actions ────────────────────────────────────────────────────────

  Widget _buildQuickActions(BuildContext context) {
    return GridView.count(
      physics: const NeverScrollableScrollPhysics(),
      shrinkWrap: true,
      crossAxisCount: 2,
      mainAxisSpacing: 10,
      crossAxisSpacing: 10,
      childAspectRatio: 1.35,
      children: [
        _quickAccessTile(
          icon: Icons.emergency_outlined,
          label: 'Emergency',
          subtitle: 'Tap to get help',
          iconBackground: const Color(0xFFFCEBEB),
          iconColor: const Color(0xFFA32D2D),
          onTap: () => _showSupportSheet(context),
        ),
        _quickAccessTile(
          icon: Icons.health_and_safety_outlined,
          label: 'Medical help',
          subtitle: 'Find support',
          iconBackground: const Color(0xFFE6F1FB),
          iconColor: const Color(0xFF185FA5),
          onTap: () => _showSupportSheet(context),
        ),
        _quickAccessTile(
          icon: Icons.inventory_2_outlined,
          label: 'Gear assist',
          subtitle: 'File a claim',
          iconBackground: const Color(0xFFEAF3DE),
          iconColor: const Color(0xFF3B6D11),
          onTap: () => _showQuickClaimSheet(context),
        ),
        _quickAccessTile(
          icon: Icons.tips_and_updates_outlined,
          label: 'Safety tips',
          subtitle: 'View advisories',
          iconBackground: const Color(0xFFFAEEDA),
          iconColor: const Color(0xFFBA7517),
          onTap: () => _showNotificationsSheet(context),
        ),
      ],
    );
  }

  Widget _quickAccessTile({
    required IconData icon,
    required String label,
    required String subtitle,
    required Color iconBackground,
    required Color iconColor,
    required VoidCallback onTap,
  }) {
    return InkWell(
      borderRadius: BorderRadius.circular(16),
      onTap: onTap,
      child: Container(
        padding: const EdgeInsets.fromLTRB(12, 12, 10, 10),
        decoration: BoxDecoration(
          color: AppColors.cardBackground,
          borderRadius: BorderRadius.circular(16),
          border: Border.all(color: AppColors.border),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Container(
              width: 30,
              height: 30,
              decoration: BoxDecoration(
                color: iconBackground,
                borderRadius: BorderRadius.circular(8),
              ),
              child: Icon(icon, size: 16, color: iconColor),
            ),
            const SizedBox(height: 8),
            Text(
              label,
              style: const TextStyle(
                fontSize: 16,
                height: 1.1,
                fontWeight: FontWeight.w700,
                color: AppColors.textPrimary,
              ),
            ),
            const SizedBox(height: 3),
            Text(
              subtitle,
              style: const TextStyle(
                fontSize: 12,
                color: AppColors.textSecondary,
              ),
            ),
          ],
        ),
      ),
    );
  }

  // ─── Metrics row ──────────────────────────────────────────────────────────

  Widget _buildMetricsRow(
    User user,
    NumberFormat currencyFormat, {
    required double earningsProtected,
    required double? totalEarnings,
  }) {
    return Row(
      children: [
        Expanded(
          child: _metricCard(
            title: 'Earnings Protected',
            value: '₹${currencyFormat.format(earningsProtected)}',
            subtitle: 'Parametric coverage active',
            icon: Icons.shield,
            iconBackground: AppColors.accentLight,
            iconColor: AppColors.primary,
          ),
        ),
        const SizedBox(width: 12),
        Expanded(
          child: _metricCard(
            title: 'Total Earnings',
            value:
                totalEarnings == null ? 'Not Synced' : '₹${currencyFormat.format(totalEarnings)}',
            subtitle: totalEarnings == null
                ? 'Pending sync from ${user.platform}'
                : 'Synced from ${user.platform}',
            icon: Icons.account_balance_wallet_outlined,
            iconBackground: AppColors.infoLight,
            iconColor: AppColors.info,
          ),
        ),
      ],
    );
  }

  Widget _metricCard({
    required String title,
    required String value,
    required String subtitle,
    required IconData icon,
    required Color iconBackground,
    required Color iconColor,
  }) {
    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: AppColors.cardBackground,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: AppColors.border),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Container(
            width: 30,
            height: 30,
            decoration: BoxDecoration(
              color: iconBackground,
              borderRadius: BorderRadius.circular(9),
            ),
            child: Icon(icon, size: 16, color: iconColor),
          ),
          const SizedBox(height: 10),
          Text(
            title.toUpperCase(),
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
            style: const TextStyle(
              fontSize: 10,
              fontWeight: FontWeight.w700,
              color: AppColors.textTertiary,
              letterSpacing: 0.7,
            ),
          ),
          const SizedBox(height: 6),
          Text(
            value,
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
            style: const TextStyle(
              fontSize: 18,
              fontWeight: FontWeight.w800,
              color: AppColors.textPrimary,
              letterSpacing: -0.2,
            ),
          ),
          const SizedBox(height: 4),
          Text(
            subtitle,
            style: const TextStyle(
              fontSize: 11,
              color: AppColors.textSecondary,
            ),
          ),
        ],
      ),
    );
  }

  // ─── Weekly snapshot ──────────────────────────────────────────────────────

  Widget _buildWeeklySnapshot(
    NumberFormat currencyFormat, {
    required int coveredDaysLeft,
    required int claimsProcessedThisWeek,
    required double payoutThisWeek,
  }) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            Expanded(
              child: _miniStatCard(
                title: 'Covered Days Left',
                value: '$coveredDaysLeft',
                icon: Icons.calendar_today_outlined,
                iconColor: AppColors.info,
                iconBackground: AppColors.infoLight,
              ),
            ),
            const SizedBox(width: 10),
            Expanded(
              child: _miniStatCard(
                title: 'Claims Processed',
                value: '$claimsProcessedThisWeek',
                icon: Icons.verified_outlined,
                iconColor: AppColors.success,
                iconBackground: AppColors.successLight,
              ),
            ),
          ],
        ),
        const SizedBox(height: 10),
        _miniStatCard(
          title: 'Payout This Week',
          value: '₹${currencyFormat.format(payoutThisWeek)}',
          icon: Icons.payments_outlined,
          iconColor: AppColors.primary,
          iconBackground: AppColors.accentLight,
        ),
      ],
    );
  }

  Widget _miniStatCard({
    required String title,
    required String value,
    required IconData icon,
    required Color iconColor,
    required Color iconBackground,
  }) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: AppColors.cardBackground,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: AppColors.border),
      ),
      child: Row(
        children: [
          Container(
            width: 30,
            height: 30,
            decoration: BoxDecoration(
              color: iconBackground,
              borderRadius: BorderRadius.circular(8),
            ),
            child: Icon(icon, size: 16, color: iconColor),
          ),
          const SizedBox(width: 10),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  title,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(
                    fontSize: 11,
                    fontWeight: FontWeight.w600,
                    color: AppColors.textSecondary,
                  ),
                ),
                const SizedBox(height: 2),
                Text(
                  value,
                  style: const TextStyle(
                    fontSize: 17,
                    fontWeight: FontWeight.w800,
                    color: AppColors.textPrimary,
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  // ─── Recent claims ────────────────────────────────────────────────────────

  Widget _buildRecentClaims(
    List<Claim> claims,
    NumberFormat currencyFormat,
    DateFormat dateFormat,
  ) {
    final recentClaims = claims.toList()
      ..sort((left, right) => right.date.compareTo(left.date));

    final latestClaim = recentClaims.take(1).toList();

    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: AppColors.cardBackground,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: AppColors.border),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          if (latestClaim.isEmpty)
            const Text(
              'No claims yet',
              style: TextStyle(
                fontSize: 13,
                fontWeight: FontWeight.w600,
                color: AppColors.textSecondary,
              ),
            )
          else
            ...latestClaim.map(
            (claim) => Row(
              children: [
                Container(
                  width: 34,
                  height: 34,
                  decoration: BoxDecoration(
                    color: claim.typeColor.withValues(alpha: 0.14),
                    borderRadius: BorderRadius.circular(9),
                  ),
                  child: Icon(claim.typeIcon, size: 18, color: claim.typeColor),
                ),
                const SizedBox(width: 10),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        '${claim.typeShortName} · ${claim.id}',
                        style: const TextStyle(
                          fontSize: 13,
                          fontWeight: FontWeight.w700,
                          color: AppColors.textPrimary,
                        ),
                      ),
                      Text(
                        dateFormat.format(claim.date),
                        style: const TextStyle(
                          fontSize: 11,
                          color: AppColors.textSecondary,
                        ),
                      ),
                    ],
                  ),
                ),
                const SizedBox(width: 8),
                Column(
                  crossAxisAlignment: CrossAxisAlignment.end,
                  children: [
                    Text(
                      '₹${currencyFormat.format(claim.amount)}',
                      style: const TextStyle(
                        fontSize: 13,
                        fontWeight: FontWeight.w700,
                        color: AppColors.textPrimary,
                      ),
                    ),
                    const SizedBox(height: 2),
                    Container(
                      padding: const EdgeInsets.symmetric(
                          horizontal: 8, vertical: 3),
                      decoration: BoxDecoration(
                        color: claim.statusColor.withValues(alpha: 0.14),
                        borderRadius: BorderRadius.circular(999),
                      ),
                      child: Text(
                        claim.statusLabel,
                        style: TextStyle(
                          fontSize: 10,
                          fontWeight: FontWeight.w600,
                          color: claim.statusColor,
                        ),
                      ),
                    ),
                  ],
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  // ─── Next billing ─────────────────────────────────────────────────────────

  Widget _buildNextBillingCard(BuildContext context, InsurancePlan activePlan) {
    final nextDebitDate = DateFormat('EEE, d MMM')
        .format(DateTime.now().add(const Duration(days: 3)));

    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: AppColors.cardBackground,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: AppColors.border),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            '₹${activePlan.weeklyPremium} auto-debit on $nextDebitDate',
            style: const TextStyle(
              fontSize: 13,
              color: AppColors.textSecondary,
            ),
          ),
          const SizedBox(height: 12),
          Row(
            children: [
              Expanded(
                child: OutlinedButton.icon(
                  onPressed: () => _openCoverage(context),
                  icon: const Icon(Icons.tune, size: 18),
                  label: const Text('Manage Plan'),
                  style: OutlinedButton.styleFrom(
                    foregroundColor: AppColors.primary,
                    side: const BorderSide(color: AppColors.border),
                    padding: const EdgeInsets.symmetric(vertical: 12),
                    shape: RoundedRectangleBorder(
                      borderRadius: BorderRadius.circular(12),
                    ),
                  ),
                ),
              ),
              const SizedBox(width: 10),
              Expanded(
                child: OutlinedButton.icon(
                  onPressed: () => _showSupportSheet(context),
                  icon: const Icon(Icons.chat_bubble_outline, size: 18),
                  label: const Text('Support'),
                  style: OutlinedButton.styleFrom(
                    foregroundColor: AppColors.primary,
                    side: const BorderSide(color: AppColors.border),
                    padding: const EdgeInsets.symmetric(vertical: 12),
                    shape: RoundedRectangleBorder(
                      borderRadius: BorderRadius.circular(12),
                    ),
                  ),
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }

  // ─── Navigation helpers ───────────────────────────────────────────────────

  void _openClaims(BuildContext context) => _switchToTab(context, 1);
  void _openCoverage(BuildContext context) => _switchToTab(context, 2);
  void _openProfile(BuildContext context) => _switchToTab(context, 4);
  void _openPayouts(BuildContext context) => _switchToTab(context, 3);

  void _switchToTab(BuildContext context, int index) {
    TabRouter.switchTo(index);
    Navigator.of(context).popUntil((route) => route.isFirst);
  }

  // ─── Bottom sheets ────────────────────────────────────────────────────────

  void _showNotificationsSheet(BuildContext context) {
    showModalBottomSheet<void>(
      context: context,
      showDragHandle: true,
      builder: (sheetContext) {
        return ListView(
          shrinkWrap: true,
          padding: const EdgeInsets.fromLTRB(16, 8, 16, 20),
          children: const [
            ListTile(
              leading: Icon(Icons.cloud_done_outlined),
              title: Text("Today's risk data synced"),
              subtitle: Text('Coverage triggers updated 5 min ago'),
            ),
            ListTile(
              leading: Icon(Icons.account_balance_wallet_outlined),
              title: Text('Weekly debit reminder'),
              subtitle: Text('Premium auto-debit due in 3 days'),
            ),
            ListTile(
              leading: Icon(Icons.support_agent_outlined),
              title: Text('Support response available'),
              subtitle: Text('A specialist replied to your last query'),
            ),
          ],
        );
      },
    );
  }

  void _showQuickMenuSheet(BuildContext context) {
    showModalBottomSheet<void>(
      context: context,
      showDragHandle: true,
      builder: (sheetContext) {
        return SafeArea(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              ListTile(
                leading: const Icon(Icons.person_outline),
                title: const Text('Profile'),
                onTap: () {
                  Navigator.pop(sheetContext);
                  _openProfile(context);
                },
              ),
              ListTile(
                leading: const Icon(Icons.receipt_long_outlined),
                title: const Text('Claims'),
                onTap: () {
                  Navigator.pop(sheetContext);
                  _openClaims(context);
                },
              ),
              ListTile(
                leading: const Icon(Icons.shield_outlined),
                title: const Text('Coverage'),
                onTap: () {
                  Navigator.pop(sheetContext);
                  _openCoverage(context);
                },
              ),
              ListTile(
                leading: const Icon(Icons.payments_outlined),
                title: const Text('Payouts'),
                onTap: () {
                  Navigator.pop(sheetContext);
                  _openPayouts(context);
                },
              ),
            ],
          ),
        );
      },
    );
  }

  void _showSupportSheet(BuildContext context) {
    showModalBottomSheet<void>(
      context: context,
      showDragHandle: true,
      builder: (sheetContext) {
        return SafeArea(
          child: Padding(
            padding: const EdgeInsets.fromLTRB(16, 8, 16, 20),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text(
                  'Support',
                  style: TextStyle(fontSize: 20, fontWeight: FontWeight.w700),
                ),
                const SizedBox(height: 10),
                const Text('Choose how you want help with your policy or claims.'),
                const SizedBox(height: 12),
                ListTile(
                  contentPadding: EdgeInsets.zero,
                  leading: const Icon(Icons.call_outlined),
                  title: const Text('Call support'),
                  subtitle: const Text('+91 1800 00 0000'),
                  onTap: () {
                    Navigator.pop(sheetContext);
                    ScaffoldMessenger.of(context).showSnackBar(
                      const SnackBar(content: Text('Calling support is coming soon.')),
                    );
                  },
                ),
                ListTile(
                  contentPadding: EdgeInsets.zero,
                  leading: const Icon(Icons.chat_outlined),
                  title: const Text('Chat with us'),
                  subtitle: const Text('Average wait: under 2 min'),
                  onTap: () {
                    Navigator.pop(sheetContext);
                    ScaffoldMessenger.of(context).showSnackBar(
                      const SnackBar(content: Text('Live chat will be available soon.')),
                    );
                  },
                ),
                ListTile(
                  contentPadding: EdgeInsets.zero,
                  leading: const Icon(Icons.help_outline),
                  title: const Text('View claim guide'),
                  subtitle: const Text('See how disputes are reviewed'),
                  onTap: () {
                    Navigator.pop(sheetContext);
                    _openCoverage(context);
                  },
                ),
              ],
            ),
          ),
        );
      },
    );
  }

  void _showQuickClaimSheet(BuildContext context) {
    showModalBottomSheet<void>(
      context: context,
      showDragHandle: true,
      builder: (sheetContext) {
        return SafeArea(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              ListTile(
                leading: const Icon(Icons.report_problem_outlined),
                title: const Text('Raise payout dispute'),
                subtitle: const Text('Missing trigger or delayed payout'),
                onTap: () {
                  Navigator.pop(sheetContext);
                  _openClaims(context);
                },
              ),
              ListTile(
                leading: const Icon(Icons.payments_outlined),
                title: const Text('Open payouts ledger'),
                subtitle: const Text('Track your latest credits and status'),
                onTap: () {
                  Navigator.pop(sheetContext);
                  _openPayouts(context);
                },
              ),
              ListTile(
                leading: const Icon(Icons.support_agent_outlined),
                title: const Text('Contact support'),
                subtitle: const Text('Talk to a specialist'),
                onTap: () {
                  Navigator.pop(sheetContext);
                  _showSupportSheet(context);
                },
              ),
            ],
          ),
        );
      },
    );
  }

  // ─── Primary actions ──────────────────────────────────────────────────────

  Widget _buildPrimaryActions(BuildContext context) {
    return Column(
      children: [
        InkWell(
          borderRadius: BorderRadius.circular(18),
          onTap: () {
            _showQuickClaimSheet(context);
          },
          child: Container(
            width: double.infinity,
            padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 16),
            decoration: BoxDecoration(
              color: AppColors.primary,
              borderRadius: BorderRadius.circular(18),
            ),
            child: const Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      'Raise Dispute',
                      style: TextStyle(
                        fontSize: 17,
                        fontWeight: FontWeight.w700,
                        color: Colors.white,
                      ),
                    ),
                    SizedBox(height: 3),
                    Text(
                      'Report missed trigger or payout issue',
                      style: TextStyle(
                        fontSize: 12,
                        color: Colors.white70,
                      ),
                    ),
                  ],
                ),
                Icon(Icons.arrow_forward_rounded, color: Colors.white),
              ],
            ),
          ),
        ),
        const SizedBox(height: 10),
        Row(
          children: [
            Expanded(
              child: OutlinedButton.icon(
                onPressed: () {
                  _openCoverage(context);
                },
                icon: const Icon(Icons.description_outlined, size: 18),
                label: const Text('Coverage'),
                style: OutlinedButton.styleFrom(
                  foregroundColor: AppColors.primary,
                  side: const BorderSide(color: AppColors.border),
                  padding: const EdgeInsets.symmetric(vertical: 13),
                  shape: RoundedRectangleBorder(
                    borderRadius: BorderRadius.circular(14),
                  ),
                ),
              ),
            ),
            const SizedBox(width: 10),
            Expanded(
              child: OutlinedButton.icon(
                onPressed: () {
                  _openClaims(context);
                },
                icon: const Icon(Icons.history, size: 18),
                label: const Text('History'),
                style: OutlinedButton.styleFrom(
                  foregroundColor: AppColors.primary,
                  side: const BorderSide(color: AppColors.border),
                  padding: const EdgeInsets.symmetric(vertical: 13),
                  shape: RoundedRectangleBorder(
                    borderRadius: BorderRadius.circular(14),
                  ),
                ),
              ),
            ),
          ],
        ),
      ],
    );
  }

  // ─── Section header ───────────────────────────────────────────────────────

  Widget _buildSectionHeader(
    String title, {
    String? actionText,
    VoidCallback? onTap,
  }) {
    return Row(
      children: [
        Expanded(
          child: Text(
            title,
            style: const TextStyle(
              fontSize: 16,
              fontWeight: FontWeight.w700,
              color: AppColors.textPrimary,
            ),
          ),
        ),
        if (actionText != null)
          TextButton(
            onPressed: onTap ?? () {},
            style: TextButton.styleFrom(
              padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
              minimumSize: const Size(0, 36),
              tapTargetSize: MaterialTapTargetSize.shrinkWrap,
            ),
            child: Text(
              actionText,
              style: const TextStyle(
                fontSize: 12,
                fontWeight: FontWeight.w600,
                color: AppColors.primary,
              ),
            ),
          ),
      ],
    );
  }

  // ─── Account options sheet ────────────────────────────────────────────────

  void _showAccountOptions(BuildContext context, User user) {
    showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      backgroundColor: Colors.transparent,
      builder: (sheetContext) {
        return Container(
          height: MediaQuery.of(sheetContext).size.height * 0.82,
          decoration: const BoxDecoration(
            color: AppColors.scaffoldBackground,
            borderRadius: BorderRadius.vertical(top: Radius.circular(26)),
          ),
          child: SafeArea(
            top: false,
            child: Padding(
              padding: const EdgeInsets.fromLTRB(20, 12, 20, 20),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Center(
                    child: Container(
                      width: 42,
                      height: 4,
                      decoration: BoxDecoration(
                        color: AppColors.border,
                        borderRadius: BorderRadius.circular(999),
                      ),
                    ),
                  ),
                  const SizedBox(height: 16),
                  const Text(
                    'Account',
                    style: TextStyle(
                      fontSize: 34,
                      fontWeight: FontWeight.w800,
                      color: AppColors.textPrimary,
                      letterSpacing: -0.6,
                    ),
                  ),
                  const SizedBox(height: 16),
                  Container(
                    width: double.infinity,
                    padding: const EdgeInsets.all(16),
                    decoration: BoxDecoration(
                      color: AppColors.cardBackground,
                      borderRadius: BorderRadius.circular(16),
                      border: Border.all(color: AppColors.border),
                    ),
                    child: Row(
                      children: [
                        Container(
                          width: 52,
                          height: 52,
                          decoration: const BoxDecoration(
                            color: AppColors.primary,
                            shape: BoxShape.circle,
                          ),
                          child: Center(
                            child: Text(
                              user.name.substring(0, 1).toUpperCase(),
                              style: const TextStyle(
                                fontSize: 24,
                                fontWeight: FontWeight.w600,
                                color: Colors.white,
                              ),
                            ),
                          ),
                        ),
                        const SizedBox(width: 12),
                        Expanded(
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text(
                                user.name,
                                maxLines: 1,
                                overflow: TextOverflow.ellipsis,
                                style: const TextStyle(
                                  fontSize: 20,
                                  fontWeight: FontWeight.w700,
                                  color: AppColors.textPrimary,
                                  letterSpacing: -0.2,
                                ),
                              ),
                              const SizedBox(height: 2),
                              Text(
                                user.phone,
                                style: const TextStyle(
                                  fontSize: 15,
                                  color: AppColors.textSecondary,
                                ),
                              ),
                            ],
                          ),
                        ),
                      ],
                    ),
                  ),
                  const SizedBox(height: 22),
                  const Text(
                    'Manage',
                    style: TextStyle(
                      fontSize: 17,
                      fontWeight: FontWeight.w700,
                      color: AppColors.textPrimary,
                    ),
                  ),
                  const SizedBox(height: 8),
                  Expanded(
                    child: ListView(
                      padding: EdgeInsets.zero,
                      children: [
                        _accountOption(
                          icon: Icons.person_outline,
                          title: 'Profile details',
                          onTap: () {
                            Navigator.pop(sheetContext);
                            _openProfile(context);
                          },
                        ),
                        _accountOption(
                          icon: Icons.description_outlined,
                          title: 'Policy details',
                          onTap: () {
                            Navigator.pop(sheetContext);
                            _openCoverage(context);
                          },
                        ),
                        _accountOption(
                          icon: Icons.receipt_long_outlined,
                          title: 'Claims and disputes',
                          onTap: () {
                            Navigator.pop(sheetContext);
                            _openClaims(context);
                          },
                        ),
                        _accountOption(
                          icon: Icons.payments_outlined,
                          title: 'Plan and pricing',
                          onTap: () {
                            Navigator.pop(sheetContext);
                            _openCoverage(context);
                          },
                        ),
                        _accountOption(
                          icon: Icons.payments_outlined,
                          title: 'Payouts ledger',
                          onTap: () {
                            Navigator.pop(sheetContext);
                            _openPayouts(context);
                          },
                        ),
                        _accountOption(
                          icon: Icons.help_outline,
                          title: 'Help and support',
                          onTap: () {
                            Navigator.pop(sheetContext);
                            _showSupportSheet(context);
                          },
                        ),
                        _accountOption(
                          icon: Icons.language,
                          title: 'Language',
                          onTap: () {
                            Navigator.pop(sheetContext);
                            ScaffoldMessenger.of(context).showSnackBar(
                              const SnackBar(
                                content:
                                    Text('Language settings will be added next.'),
                              ),
                            );
                          },
                        ),
                        _accountOption(
                          icon: Icons.logout,
                          title: 'Log out',
                          isDestructive: true,
                          onTap: () {
                            Navigator.pop(sheetContext);
                            Navigator.pushNamedAndRemoveUntil(
                              context,
                              AppRoutes.welcome,
                              (route) => false,
                            );
                          },
                        ),
                      ],
                    ),
                  ),
                ],
              ),
            ),
          ),
        );
      },
    );
  }

  Widget _accountOption({
    required IconData icon,
    required String title,
    required VoidCallback onTap,
    bool isDestructive = false,
  }) {
    final textColor =
        isDestructive ? AppColors.error : AppColors.textPrimary;

    return ListTile(
      onTap: onTap,
      contentPadding: const EdgeInsets.symmetric(vertical: 2),
      leading: Icon(icon, color: textColor, size: 25),
      title: Text(
        title,
        style: TextStyle(
          fontSize: 17,
          fontWeight: FontWeight.w500,
          color: textColor,
        ),
      ),
      trailing: Icon(
        Icons.chevron_right,
        color:
            isDestructive ? AppColors.error : AppColors.textSecondary,
      ),
    );
  }

  Widget _headerIconButton({
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
            border: Border.all(
              color: Colors.white.withValues(alpha: 0.28),
            ),
          ),
          child: Icon(icon, size: 21, color: AppColors.textPrimary),
        ),
      ),
    );
  }
}

// ─── Background painter ────────────────────────────────────────────────────

class _HomeTopBackgroundPainter extends CustomPainter {
  const _HomeTopBackgroundPainter({required this.topHeight});

  final double topHeight;

  @override
  void paint(Canvas canvas, Size size) {
    final backgroundPath = Path()
      ..moveTo(0, 0)
      ..lineTo(0, topHeight - 18)
      ..cubicTo(
        size.width * 0.12,
        topHeight + 8,
        size.width * 0.28,
        topHeight - 28,
        size.width * 0.44,
        topHeight - 4,
      )
      ..cubicTo(
        size.width * 0.60,
        topHeight + 18,
        size.width * 0.78,
        topHeight + 2,
        size.width,
        topHeight - 16,
      )
      ..lineTo(size.width, 0)
      ..close();

    final paint = Paint()
      ..shader = const LinearGradient(
        begin: Alignment.topCenter,
        end: Alignment.bottomCenter,
        colors: [
          Color(0xFFF9FAF7),
          Color(0xFFF2F6F2),
          Color(0xFFEAF2EE),
        ],
      ).createShader(
        Rect.fromLTWH(0, 0, size.width, topHeight + 40),
      );

    canvas.drawPath(backgroundPath, paint);

    final accentPaint = Paint()
      ..color = AppColors.primary.withValues(alpha: 0.08)
      ..style = PaintingStyle.fill;

    canvas.drawCircle(Offset(size.width * 0.1, size.height * 0.18), 56, accentPaint);
    canvas.drawCircle(Offset(size.width * 0.86, size.height * 0.26), 36, accentPaint);
  }

  @override
  bool shouldRepaint(covariant _HomeTopBackgroundPainter oldDelegate) {
    return oldDelegate.topHeight != topHeight;
  }
}

// ─── View data model ───────────────────────────────────────────────────────

class _HomeViewData {
  const _HomeViewData({
    required this.user,
    required this.claims,
    required this.latestClaim,
    required this.autoTriggerMessages,
    required this.activePlan,
    required this.earningsProtected,
    required this.totalEarnings,
    required this.coveredDaysLeft,
    required this.claimsProcessedThisWeek,
    required this.payoutThisWeek,
  });

  final User user;
  final List<Claim> claims;
  final Claim? latestClaim;
  final List<String> autoTriggerMessages;
  final InsurancePlan activePlan;
  final double earningsProtected;
  final double? totalEarnings;
  final int coveredDaysLeft;
  final int claimsProcessedThisWeek;
  final double payoutThisWeek;
}