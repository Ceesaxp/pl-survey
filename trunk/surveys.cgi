#!/usr/bin/perl

package survey;

use strict qw/vars/;
my $start = (times)[0];
use warnings;
use utf8;

use CGI qw/:standard *div *table/;
use CGI::Cookie;
use CGI::Carp qw/fatalsToBrowser warningsToBrowser/;
use XML::Simple;
use HTTP::Date qw/time2iso time2str/;
use FileHandle;
#use Data::Dumper; # for debugging purposes, mostly
use vars qw/$q $path $survey_type @pgdebug $debug $survey/;

use constant VERSION => '0.4.2';
use constant CONFIG_DIR => 'cgi-data/surveys';
use constant SCRIPT_URL => '/cgi-bin/surveys.cgi';
use constant COOKIE_NAME => 'net.citigroup.russia.cgi.surveys.soe';

# A little help for debugginh...
$ENV{REQUEST_METHOD} = 'GET' unless defined $ENV{REQUEST_METHOD};

$q = new CGI;
$path = $q->path_info();
$survey_type = 'Surveys';

# Enable debugging
# Debug levels:
#  0 - no debug
#  1 - debug to page only
#  2 - debug to page and log
$debug = 0;
#binmode STDERR, ":utf8";
binmode STDOUT, ":utf8";

# HTTP method processing routines
#
# They all take PATH regexp and code block CODE as parameter, compare current
# path_info to the PATH regexp and execute CODE block if they match.
sub GET($$) {
  debug_trace('info','Entering GET');
  my ($path, $code) = @_;
  return unless $q->request_method eq 'GET' or $q->request_method eq 'HEAD';
  return unless $q->path_info =~ $path;
  $code->();
  exit;
}

sub POST($$) {
  debug_trace('info','Entering POST');
  my ($path, $code) = @_;
  return unless $q->request_method eq 'POST';
  return unless $q->path_info =~ $path;
  $code->();
  exit;
}

sub PUT($$) {
  debug_trace('info','Entering PUT');
  my ($path, $code) = @_;
  return unless $q->request_method eq 'PUT';
  return unless $q->path_info =~ $path;
  $code->();
  exit;
}

sub DELETE($$) {
  debug_trace('info','Entering DELETE');
  my ($path, $code) = @_;
  return unless $q->request_method eq 'DELETE';
  return unless $q->path_info =~ $path;
  $code->();
  exit;
}


# Function: barf(STATUS,TITLE,MESSAGE)
#
# Sends HTTP status code STATUS in response, setting window title to TITLE and
# providing an optional MESSAGE text
sub barf($$;$) {
  debug_trace('info','Entering barf');
  my ($status, $title, $message) = @_;
  my $t = time2str();
  carp <<"EOH"
HTTP/1.0 $status
Date: $t
Content-Type: text/html; charset=utf-8

<html><head><title>$title</title></head><body><h1>$title</h1><p>$message</p></body></html>
EOH
}


# Function: get_local_path(ID)
#
# Returns the ful path to a file requested.
sub get_local_path($) {
  debug_trace('info','Entering get_local_path');
  my $id = shift;
  return CONFIG_DIR.'/'.$id.'.xml';
}

# Function: absolute_url(PATH)
#
# Returns full URL (host, port, path) to a given PATH
sub absolute_url($) {
  debug_trace('info','Entering absolute_url');
  my $path = shift;
  return $q->url() . $path;
}


sub debug_trace ($@) {
  return unless $survey::debug;
  my $status = shift || 'info';
  my @msg = @_;
  push @pgdebug, p({class=>'debug_'.$status},@msg);
  if ($survey::debug > 1) {
    # if debug level set to verbose, also print to log
    map { print STDERR $_." \n"; } @msg;
  }
}


#
# Request dispatchers
#
eval {

  # catch the case when we're called directly, redirect to surveys list
  GET qr{^/?$} => sub {
    print $q->redirect( absolute_url('/survey/') );
  };

  # self documentatation
  GET qr{^/doc/?$} => sub {
    show_documentation();
  };

  # surveys list
  GET qr{^/survey/?$} => sub {
    print standard_headers('Available Surveys');
    print list_all_surveys();
  };

  # show survey
  GET qr{^/survey/([-_[:alnum:]]+)/?$} => sub {
    my $sid = $1;
    $survey = read_survey(get_local_path($sid)) unless defined $survey;
    authenticate_user($sid) if ( $survey->{'protected'} =~ m/yes/i
                                  and !survey_cookie_set_p($sid) );
    already_taken($sid) if survey_cookie_set_p($sid, 'taken');
    print standard_headers($survey->{'description'}, 0, $sid);
    print build_form($sid, $survey);
    print form_extras($sid);
  };

  # poll graph
  GET qr{^/survey/graph/([-_[:alnum:]]+)/?$} => sub {
    my $sid = $1;
    $survey = read_survey(get_local_path($sid)) unless defined $survey;
    print standard_headers($survey->{'description'}, 0, $sid);
    print show_survey_stats($sid);
  };

  # survey rporting
  GET qr{^/survey/report/([-_[:alnum:]]+)/?$} => sub {
    my $sid = $1;
    $survey = read_survey(get_local_path($sid)) unless defined $survey;
    authenticate_admin_user ($sid) unless survey_admin_cookie_set_p();
    print standard_headers ($survey->{'description'}, 0, $sid);
    print build_survey_report ($sid);
  };

  GET qr{^/survey/stats/([-_[:alnum:]]+)/?$} => sub {
    my $sid = $1;
    $survey = read_survey(get_local_path($sid)) unless defined $survey;
    authenticate_admin_user($sid) unless survey_admin_cookie_set_p();
    print standard_headers($survey->{'description'}, 0, $sid);
    print build_quiz_status_report($sid);
  };

  # editing survey content !!FIXME!!
  GET qr{^/survey/edit/([-_[:alnum:]]+)$} => sub {
    my $sid = $1;
    print standard_headers('Edit Survey Parameters') && survey_edit_form($sid);
  };

  # accept answers to a survey
  POST qr{^/survey/answer/([-_[:alnum:]]+)$} => sub {
    my $sid = $1;
    my $data = $q->Vars;
    already_taken($sid) if survey_cookie_set_p($sid,'taken');
    validate_and_store_answers($sid, $data);
    exit;
  };


  # Autheticate and redirect to the survey if all is fine or to no_entry page if
  # not.
  POST qr{^/survey/auth/([-_[:alnum:]]+)$} => sub {
    my $sid = $1;
    my $data = $q->Vars;
    $survey = read_survey(get_local_path($sid)) unless defined $survey;

    no_entry() if ($data->{skey} ne $survey->{accessKey});
    set_auth_cookie($sid, $data->{'sso'});

    # force a redirect
    print qq{<meta http-equiv="refresh" content="0;URL=/cgi-bin/surveys.cgi/survey/$sid">\n};
  };

  # update survey content
  PUT qr{^/survey/([-_[:alnum:]]+)$} => sub {
    barf 200, 'Got update request', "For survey $1.";
  }

};


# Function: survey_edit_form(SURVEY_ID)
#
# Build and display form to make changes to survey SURVEY_ID.
sub survey_edit_form ($) {
  debug_trace('info','Entering survey_edit_form ');
  my $sid = shift;
  print $q->p('Sorry, not yet implemented.'),
    p(a({href=>absolute_url('/survey/')},'Return to survey front')),
      end_html;
}


# Function: glob_dir()
#
# Reads CONFIG_DIR and returns the list of XML files in it.
#
# Why are we not using Perl's glob?  Because there was no ending to "mysterious"
# data losses with it -- shift not returning anything, etc.  And in any case --
# glob does a call to shell, whereas opendir does not.
sub glob_dir () {
  debug_trace('info','Entering glob_dir ');
  opendir(DIR, CONFIG_DIR);
  my @files = grep { /\.xml$/ } readdir(DIR);
  closedir(DIR);
  return @files;
}

# Function: list_all_surveys(STATUS)
#
# Lists all surveys that match STATUS (by default lists all defined surveys).
sub list_all_surveys(;$) {
  debug_trace('info','Entering list_all_surveys');
  my $status = shift || 'ALL'; # by default we show all surveys
  my @surveys;
  my @page;

  for my $fn ( glob_dir() ) {
    next unless $fn =~ m{([^/]+)\.xml$};
    push @surveys, survey_title_link($1);
  }

  my $num_surveys = scalar @surveys || 0;
  push @page, $q->h2('Available surveys'),
    p('There ', ($num_surveys == 1 ? 'is' : 'are'),
      $num_surveys,
      'survey'.($num_surveys == 1 ? '' : 's'),
      ' defined') if ($num_surveys > 0);
  push @page, $q->h2('No surveys defined.') if ($num_surveys == 0);
  push @page, $q->ul(@surveys),
    $q->p('You can either run (take) any of these surveys or administer them.'),
      $q->p('Note that you have to be a survey admin to make changes to survey setups.'),
        $q->end_html;
  return @page;
}


# Function: read_survey(SURVEY_ID)
#
# Read survey definition file and store results in a hashref
#
# Parameters:
#   SURVEY_ID - Survey ID.  We will look for the file with name SURVEY_ID.xml in configuration directory.
#
# Returns:
#   Hash reference containing the representation of XML file.
sub read_survey ($) {
  debug_trace('info','Entering read_survey ');
  my $survey_file = shift;
  confess "No name has been supplied for survey file!" unless defined $survey_file;
  confess "The file `$survey_file' does not exist!" if !(-e $survey_file);
  my $xs = new XML::Simple (ForceArray => 1, KeepRoot => 0, KeyAttr => ['key']);
  return $xs->XMLin($survey_file) or debug_trace('error',$@);
}


# Function: standard_headers(TITLE)
#
# Outputs a standard set of "front matter" -- fills in <HEAD> with required
# JS/CSS includes, creates <DIV> for branding data, fires off Event.observe()
# watchers.
#
# Parameters:
#   TITLE        - page title (required)
#   NOHEADER     - suppress output of HTTP header (optional, defaults to no suppress)
#   SURVEY_ID    - add form reset/clear JS (optional, defaults to nothing)
#   SURVEY_TYPE  - type of a Survey (optional, used as page title)
#   COOKIE_STATE - desired survey cookie state (optional)
#
# Returns:
#   Outputs required HTML segment
sub standard_headers ($;$$$$) {
  debug_trace('info','Entering standard_headers ');
  my $title = shift;
  my $noheader = shift || 0;
  my $sid = shift;
  my $stype = shift || 'Citi M&B ';
  my $cookie_state = ( shift || $q->cookie(COOKIE_NAME.".$sid") || $sid );
  my $js;
  my (@events, @output);

  my $cookie = $q->cookie(-name    => COOKIE_NAME.".$sid",
                          -value   => $cookie_state,
                          -expires => '+30d');

  push @events,
    "\$\$('#$sid input[type=checkbox]').each( function(s) { s.checked = false; } );\n" if defined $sid;
  push @events, "opts = { descriptor : '$stype $survey_type', descriptorColor : 'blue', approvedLogo : 'citigroup' }; var header = new Branding.Header('branding', opts);";

  $js = 'Event.observe(window, "load", function() { ';
  map { $js .= $_,"\n"; } @events;
  $js .= '});';

  push @output, $q->header(-charset=>'utf-8', -cookie => $cookie) unless $noheader;
  push @output, $q->start_html(-title=>$title,
                               -encoding=>'utf-8',
                               -style=>{'src'=>['/css/surveys.css','/css/light.css']},
                               -script=>
                               [ { -type => 'text/javascript',
                                   -src      => '/lib/prototype.js'
                                 },
                                 { -type => 'text/javascript',
                                   -src      => '/lib/branding.js'
                                 },
                                 $js
                               ] );
  push @output, $q->div( { id=>'branding' }, '' );
  push @output, $q->div( { id=>'navigation' }, breadcrubms($title, $sid) );
  return @output;
}


# Function breadcrumbs(SURVEY_ID)
#
# Builds 'bread crumbs' navigation strip
sub breadcrubms($$) {
  debug_trace('info','Entering breadcrubms');
  my ($title, $sid) = @_;
  my @bcrumbs;
  push @bcrumbs, $q->li( a( { href=>'http://russia.citigroup.net/index2.htm' }, 'Citi M&amp;B Home' ) );
  push @bcrumbs, $q->li( { class=>'leftTab' }, '' );
  push @bcrumbs, $q->li( a( { href=>absolute_url('/') }, 'Surveys Home' ) );
  if (defined $sid) {
    push @bcrumbs, $q->li( { class=>'leftTab' }, '' );
    push @bcrumbs, $q->li( a( { href=>absolute_url("/survey/$sid") }, $title) );
  }
  return $q->ul( {id=>'nav'}, @bcrumbs);
}

# Function: build_form(SURVEY_ID, SURVEYOBJ)
#
# Builds the survey form
#
# Parameters:
#   SURVEY_ID - Survey ID to build the form for (required)
#   SURVEYOBJ - Parsed survey hash to extract data from (required)
#
# Returns:
#   Outputs HTML form
sub build_form ($$) {
  debug_trace('info','Entering build_form ');
  my ($sid, $survey) = @_;
  my (@page, $sso);
  $sso = fetch_survey_cookie($sid);
  push @page, $q->start_div( {-id=>'page'} );
  push @page, $q->h2( {-class=>'surveyDescription'}, $survey->{'description'} );
  push @page, $q->p( $survey->{'surveyInstructions'} );
  push @page, $q->start_div( { -class => 'survey' } );
  push @page, $q->start_form(-id=>"$sid", -method=>'post',
                           -action => absolute_url('')."/survey/answer/$sid");
  push @page, $q->hidden(-name => 'mode', -value => 'r'),
    $q->hidden(-name => 's', -value => $sid),
      $q->hidden(-name=>'sso', -value => $sso);

  my @qaset;
  map {
    my (%l, @v, $answers);
    my $question = $survey->{'question'}->{$_};
    my $gr = "s$sid:q$_";
    my $ans = $question->{'answer'}; # shortcut reference to <answer>s
    my $type = $question->{'type'};

    # labels for radio/checkbox
    map { $l{$_} = $_.'. '.$$ans{$_}{content}; push @v,"$_"; } sort keys %$ans;

    if ($type eq 'radio' || $type eq 'boolean') {
      $answers = $q->radio_group(-name => $gr,
                                 -values => \@v,
                                 -linebreak => 'true',
                                 -default => '',
                                 -labels => \%l);
    } elsif ($type eq 'multi') {
      $answers = $q->checkbox_group(-name => $gr,
                                    -values => \@v,
                                    -linebreak => 'true',
                                    -labels => \%l);
    } elsif ($type eq 'comment') {
      my $rows = $question->{'rows'} || 3;
      my $cols = $question->{'cols'} || 40;
      $answers = $q->textarea(-name=>$gr,
                              -default=>'',
                              -rows=>$rows,
                              -columns=>$cols);
      $answers .= $q->div({-class=>'help'}, wiki_format_msg());
    }
    push @qaset, $q->li($q->span({class=>'question'}, $question->{'text'}),
                        $q->div({-class=>'answers'},$answers));

  } sort {$a <=> $b} keys %{$survey->{'question'}};

  push @page, $q->ol({-class=>'qaset'}, @qaset);
  push @page, $q->div({-id=>'pollSubmit',-class=>'submit'},
                      submit('submit','Submit'));
  push @page, $q->endform();
  push @page, $q->end_div();
  push @page, $q->end_div();
  return @page;
}


# Function read_responses_for_status_report (SID)
#
# Read responses database in and arrange data in a hash for easy retreival in
# the reporting engine.
sub read_responses_for_status_report ($) {
  my $sid = shift;
  my $db = {};  # define anonymous hash to hold database in
  open my $fh, CONFIG_DIR.'/'.$sid.'.db' || debug_trace('error',$@);
  binmode $fh, ':encoding(UTF-8)';
  $survey = read_survey(get_local_path($sid)) unless defined $survey;

  while (<$fh>) {
    next if (/^#/);  # skip if start with comment sign
    s/\r\n$//; # strip CRLFs

    my @r = split /\|/;
    my @answers;
    my $l = (scalar @r) - 2;
    map {
      push @answers, m/q\d+:(.+)/;
    } @r[4..$l];
    push @answers, $r[$l+1];
    push @answers, $r[$l+2];

    my ($day, $tm) = split / /,$r[0];
    my $user = $r[1];

    $db->{$day}->{$user} = { $r[0] => { 'answers' => \@answers,
                                        'good'    => $r[$l],
                                        'bad'     => $r[$l+1] } };
    $db->{$day}->{$user}->{'times_user_day'}++;
    $db->{$day}->{'times_day'}++;
    $db->{$user}->{'times_user'}++;
    $db->{'times_total'}++;

    if ($r[$l] >= $survey->{'passRate'}) {
      $db->{$day}->{'times_pass_day'}++;
      push @{$db->{'passed_users'}}, $user;
      push @{$db->{$day}->{'passed_users'}}, $user;
      $db->{'times_pass_total'}++;
    }
  }

  close ($fh);
  return $db;
}


# Function: go_home()
#
# Generates a go to survey home link
sub go_home () {
  my $sid = $survey->{'id'}; # CAUTION! expects that $survey has been initted
                             # before!
  my $url = SCRIPT_URL;
  return <<"EOT";
<ul><li>Return to <a href="$url">CMB Surveys home</a>.</li>
<li>Return to <a href="$url/survey/$sid">this survey's front</a> page.</li>
</ul>
EOT
}


# Function: build_quiz_status_report(SID)
#
# Status report for a quiz-type survey SID
#
# SID - Survey ID to pull data out for
sub build_quiz_status_report ($) {
  my $sid = shift;
  $survey = read_survey(get_local_path($sid)) unless defined $survey;
  # bail out if this is not a test
  return "This is not a quiz/test/assessment.".go_home()
    unless ($survey->{'surveyType'} =~ m/(assessment|quiz|test|exam)/i);

  my (@passed_tod, @passed_all) = ();
  my $responses = read_responses_for_status_report($sid);

  my $d = $ARGV[1] || substr(time2iso(),0,10);
  my $s_name = $survey->{'description'};
  my $ts = localtime;
  my $taken = $responses->{'times_total'} || 0;
  my $ptotal = $responses->{'times_pass_total'} || 0;
  my $taken_tod = $responses->{$d}->{'times_day'} || 0;
  my $ptoday = $responses->{$d}->{'times_pass_day'} || 0;
  @passed_tod = @{$responses->{$d}->{'passed_users'}}
    if defined $responses->{$d}->{'passed_users'};
  @passed_all = @{$responses->{'passed_users'}}
    if defined $responses->{'passed_users'};

  @passed_tod = qw/none/ if (scalar @passed_tod == 0);
  @passed_all = qw/none/ if (scalar @passed_all == 0);

  format Report_Format =
<pre style="margin:1em;padding:1em;width:48em;border:1px solid black;">
                                                                    @<<<<<<<<<<
	                                                                  $ts
                               SUMMARY RESULTS
@||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||||
$s_name

-------------------------------------------------------------------------------
Total number of responses collected: @#####
                                     $taken
  Total number of passes:            @#####
                                     $ptotal
Number of responses today:           @#####
                                     $taken_tod
  Total passes for today:            @#####
                                     $ptoday

Users who passed today: @*
                        @passed_tod

All users who passed:   @*
                        @passed_all

-------------------------------------------------------------------------------
                                END OF REPORT
</pre>
.

  $~ = 'Report_Format';

  write;

  return;
}



# Function: autheticate_user(SURVEY_ID)
#
# If a survey requires authentication -- show a login form, take user input and
# initiate authentication.
#
# Parameters:
#   SURVEY_ID - Survey ID to perform authentication for
sub authenticate_user ($) {
  debug_trace('info','Entering authenticate_user ');
  my $sid = shift;
  debug_trace('info','In authenticate_user');
  print standard_headers('Log in', 0, $sid);
  print $q->div({id=>'auth'},
                $q->start_form(-method => 'post',
                               -action => absolute_url("/survey/auth/$sid")),
                $q->ul( {-id=>'signon'},
                        $q->li('Your SOE user name:',
                               $q->textfield('sso','',8,7)),
                        $q->li('Survey access key',
                               $q->password_field('skey','',8,50),
                               $q->span({class=>'warning'},
                                        '** Not your Windows/SOE/SSO password **'))),
                $q->div( {-class=>'submit'},
                         $q->submit('submit','Sign in')),
                $q->endform);
  gracefull_shutdown();
}


# Function authenticate_admin_user (SID)
#
# Same as authenticate_user but for admin purposes
sub authenticate_admin_user ($) {
  debug_trace('info','Entering authenticate_admin_user ');
  return 1;
}



# Function: no_entry
#
# If a user provides wrong survey access key -- tell him just that, blank out
# his survey cookie and suggest that he should re-login.
sub no_entry () {
  debug_trace('info','Entering no_entry ');
  my $c = cookie(-name    => COOKIE_NAME,
                 -value   => '',
                 -expires => '-1d');
  barf 403, 'Not authorized', 'Access key you have supplied is not correct.';
  gracefull_shutdown();
  #exit;
}


# Function: already_taken(SURVEY_ID)
#
# If "survey completed" cookie has been set, tell user that he has already done
# this survey/quiz, no need to re-take it (unless she insists).
#
# Parameters:
#   SURVEY_ID - ID for the survey
sub already_taken ($) {
  debug_trace('info','Entering already_taken ');
  print standard_headers('You have already completed this survey');
  print $q->h1('You have already taken this survey.');
  print $q->p('No worries, there is no snooping involved, but your browser tells us that you have already paticipated in this survey.');
  print $q->end_tml;
  gracefull_shutdown();
  #exit;
}


# Function: debug_print(INFO)
#
# Print out debug information INFO into STDERR.
sub debug_print (@) {
  debug_trace('info','Entering debug_print ');
  my $in = join "\n", @_;
  print STDERR "\n*** DEBUG: ${in}\n";
  return;
}


# Function: survey_title_link(ID)
#
# Returns a LI element that includes survey title, survey id and a link to
# survey page for a given survey ID.
sub survey_title_link ($) {
  debug_trace('info','Entering survey_title_link ');
  my $sid = shift;
  #debug_trace ('info','in survey_title_link');
  my $survey = read_survey(get_local_path($sid));
  #debug_trace ('info','done read_survey', $s);
  my $css = 'active';
  my @sli;
  $css = 'inactive' if ${$survey->{'active'}} =~ m/^n/i;
  push @sli, $q->li( { class => $css },
                     a( { href => absolute_url('/survey/'.$sid) },
                        $survey->{description}),' ',
                     button_link('edit',$sid,'Edit'), ' ',
                     ( ($survey->{'surveyType'} =~ m/poll|survey/i) ? button_link('graph', $sid, 'Results') : '' ),
                     span({class=>'small'},"[ $sid ]"),
                     ( $css eq 'active' ? '' : span( {class=>'status'}, ' — Inactive' ) ) );
  #debug_trace ('info',@sli);
  return join "\n", @sli;
}


sub button_link ($$) {
  debug_trace('info','Entering button_link ');
  my ( $action, $sid, $link_title ) = @_;
  return $q->a( { class => 'button', href => absolute_url("/survey/$action/$sid") }, $link_title);
}

# Function: build_survey_report(SID)
#
# Reporting for a survey SID
sub build_survey_report ($) {
  debug_trace('info','Entering build_survey_report ');
  my $sid = shift;
  my $responses = read_survey_responses($sid);
  $survey = read_survey(get_local_path($sid)) unless defined $survey;
  print $q->h1('Summary results for',$survey->{'description'});
  print $q->pre(Dumper($responses));
  return;
}


# Function read_survey_responses (SID)
#
# Read responses database in and arrange data in a hash for easy retreival in
# the reporting engine.
sub read_survey_responses ($) {
  debug_trace('info','Entering read_survey_responses ');
  my $sid = shift;
  my $db = {};  # define anonymous hash to hold database in
  open my $fh, CONFIG_DIR.'/'.$sid.'.db' || debug_trace('error',$@);
  binmode $fh, ':encoding(UTF-8)';
  my $s = read_survey(get_local_path($sid)); # local copy

  while (<$fh>) {
    next if (/^#/);             # skip comments
    my @r = split /\|/;
    my $l = (scalar @r) - 2;    # skip last 2 fields, irrelevant for polls
    $db->{'g_total'}++;         # increment total response counter
    map {
      my ($qkey,$answers) = split /:/;
      if ($qkey =~ m/^q/) {
        $qkey =~ s/^q//;          # strip off a leading 'q'
        # multiple choices (check boxes) need to be counted up differently
        my $mt = ( $s->{'question'}->{$qkey}->{'type'} eq 'multi' ? 1 : 0 );
        $db->{'resp'}->{$qkey}->{'total'}++ unless $mt;
        map {
          $db->{'resp'}->{$qkey}->{'a'}->{$_} += 1;
          $db->{'resp'}->{$qkey}->{'total'} += 1 if $mt;
        } split /\00/,$answers;
      }
    } @r[4..$l];
  }

  close ($fh);
  return $db;
}

# Function: survey_cookie_set_p
#
# Returns boolean if a survey cookie has been set
sub survey_cookie_set_p ($;$) {
  debug_trace('info','Entering survey_cookie_set_p ');
  my $sid = shift;
  my $status = shift;
  my $cookie = $q->cookie(COOKIE_NAME.".$sid");
  return 0 if not defined $cookie;
  if (defined $status) {
    ( $cookie eq $status ) ? return 1 : return 0;
  }
  # in all other cases...
  return 1;
}

# Same as above, but for admin interface -- FIXME
sub survey_admin_cookie_set_p() {
  debug_trace('info','Entering survey_admin_cookie_set_p');
  #return defined $q->cookie(ADMIN_COOKIE_NAME);
  return 1;
}


# Function set_auth_cookie
#
# Sets authenticated cooke
sub set_auth_cookie ($$) {
  debug_trace('info','Entering set_auth_cookie ');
  my ($sid) = shift;
  my ($val) = shift;
  debug_trace('info','In set_auth_cookie');
  debug_trace('info','Setting cookie value to: '.$val);
  my $cookie = $q->cookie(-name    => COOKIE_NAME.".$sid",
                          -value   => $val,
                          -expires => '+1d');
  print $q->header(-cookie => $cookie);
  return;
}


# Function: set_survey_taken_cookie
#
# Sets cookie once the survey is taken.
sub set_survey_taken_cookie ($;$$) {
  debug_trace('info','Entering set_survey_taken_cookie ');
  my $sid = shift;
  my $state = shift || 'taken';
  my $expires = shift || '+30d';
  my $cookie = $q->cookie(-name    => COOKIE_NAME.".$sid",
                          -value   => $state,
                          -expires => $expires);
  print $q->header( -charset => 'utf-8', -cookie => $cookie );
  return;
}


# Function fetch_survey_cookie
#
# Retrieve current value of survey cookie
sub fetch_survey_cookie ($) {
  my $sid = shift;
  return $q->cookie( COOKIE_NAME . ".$sid" );
}


# Function save_score(SCORE)
#
# Saves SCORE into survey log
sub save_score ($$) {
  debug_trace('info','Entering save_score ');
  my ($sid,$score) = @_;
  my $fh = new FileHandle CONFIG_DIR.'/'.$sid.'.db', O_WRONLY|O_APPEND|O_CREAT;
  if (defined $fh) {
    print $fh $score."\n";
    undef $fh;       # automatically closes the file
  } else {
    debug_print ('Bummer '.$!.': '.CONFIG_DIR.'/'.$sid.'.dat');
  }
  return;
}


# Finction: sanatize_input(VALUE)
#
# Cleans input, brute force, at least for now.
sub sanatize_input($) {
  debug_trace('info','Entering sanatize_input');
  my $val = shift;
  my $html_tags = qr(p|a|i|b|em|strong|span|script|h[1-6]|li|ol|ul|dl|dt|dd|strike|sub|sub|font|style|br|form|input|button|table|td|tr|th|tbody|thead|tfoot|div);
  $val =~ s/\|/ /g; # strip vertical bars to ensure that we don't mess up our storage
  $val =~ s/\r//g;
  $val =~ s/\n/\\n/g;
  $val =~ s/<\/?${html_tags}[^>]*\/?>//g; # strip all listed HTML tags, very
                                          # crude
  return $val;
}


# Function: validate_and_store_answers
sub validate_and_store_answers ($$) {
  debug_trace('info','Entering validate_and_store_answers ');
  my $sid = shift;
  my $data = shift;
  $survey = read_survey(get_local_path($data->{'s'}));
  my $sso = ( $q->cookie(COOKIE_NAME.".$sid") || 'ANON' );
  my $qq = scalar keys %{$survey->{question}};
  my $pr = $survey->{passRate} || 0;

  # We will hash good/bad answers and combine the submission into $answers
  # with a bit of extra meta info.
  my (%good,%bad,$answers,$t,$f,@page);

  my $ip;
  ($survey->{'logUsers'} =~ m/(yes|true)/i) ? $ip = $ENV{REMOTE_ADDR} : $ip = 'NOTSTORED';
  debug_print('info','*** Address: '.$ENV{REMOTE_ADDR});

  # Log time, SOE ID and host IP
  $answers = time2iso().'|'.$sso.'|'.$ip.'|'.$sid.'|';

  # iterate over hash keys in POST data and fillup good/bad hashes
  map {
    my ($x,$qkey) = split /:q/;
    my $qval = $data->{$_};
    $qval = sanatize_input($qval);
    $answers .= 'q'.$qkey.':'.$qval.'|' if defined $qkey;

    if (defined $qkey && defined $qval) {
      if ($survey->{question}->{$qkey}->{'answerKey'} eq $qval) {
        $good{$qkey} = $qval;
      } else {
        $bad{$qkey} = $qval unless $qkey eq ''; # remove extras, not answers
      }
    }
  } keys %{$data};

  $t = scalar keys %good;
  $f = scalar keys %bad;
  $answers .= $t.'|'.$f;
  save_score($sid,$answers);

  # the next set of actions is surveyType-dependant
  if ($survey->{'surveyType'} =~ m/test/i ||
      $survey->{'surveyType'} =~ m/assess/i) {
    # this is a test or an assessment
    push @page, $q->h1('You have completed the test, thank you.');
    my $p = round($t / $qq * 100, 2);
    push @page,
      $q->p("You have responded correctly to <strong>$t</strong> out of <strong>$qq</strong>",
            " questions (<span class='pcnt'>${p}\%</span> score).");
    push @page, $q->p('Congratulations, this is a perfect score!') if ($f == 0);

    if ($survey->{verboseResults} =~ m/yes/i) {
      if ($t >= $pr) {
        # user passed the test
        if ($f > 0) {
          push @page, $q->p('The following questions were not answered correctly:');
          my @errors;
          map {
            my $hint = $survey->{question}->{$_}->{'answerHint'};
            $hint = "($hint)" if defined $hint;
            push @errors, $q->li('Question',$_.': ',$survey->{'question'}->{$_}->{'text'},
                                 $q->ul($q->li({class=>'youra'},'Your response: ',
                                               $q->span({class=>'bad'},$bad{$_})),
                                        $q->li({class=>'correcta'},'Correct answer is: ',
                                               $q->strong(' '.$survey->{'question'}->{$_}->{'answerKey'}),
                                               $q->span({class=>'hint'},$hint))));
          } sort {$a <=> $b} keys %bad;
          push @page, $q->ul({class=>'errors'}, @errors);
          push @page, $q->p('If you want to improve your score, you can ',
                            $q->a({href=>"/cgi-bin/surveys.cgi/survey/$sid"},'take the survey again'),'.');
          clear_survey_taken_cookie($sid);      # we need to clear the cookie away to grant access
        }
        set_survey_taken_cookie($sid, 'passed');
      } else {
        # user did not pass
        set_survey_taken_cookie($sid, $sso); # we flag him as logged in
        push @page, $q->p("You need to answer at least <span class='pass'>$pr</span> questions correctly to pass.",
                          'You have not been able to attain a passing grade and should ',
                          $q->a({href=>"/cgi-bin/surveys.cgi/survey/$sid"},'take the survey again').'.');
      }
    }

  } elsif ($survey->{'surveyType'} =~ m/poll/i) {
    set_survey_taken_cookie($sid);
    push @page, $q->h1('Thank you for participating in our survey.');
    push @page, show_survey_stats($sid);
  } else {
    # bummer -- unknown survey type or it is missing
  }

  print standard_headers('Thank you', 1);
  print @page;
  print $q->end_html;
  return;
}


# Function: show_survey_stats
#
# For a poll/survey show statistics of what were participant responses
#
# Parameters:
# $sid - Survey ID
#
# Returns:
# A graph/table representing the histogram of responses
sub show_survey_stats ($) {
  debug_trace('info','Entering show_survey_stats ');
  my $sid    = shift;
  $survey    = read_survey(get_local_path($sid)) unless defined $survey;
  my $res    = read_survey_responses($sid);
  my @page;        # page struct
  my $p;
  my @comments;    # we will store the list of question IDs that are
                   # comments here for further processing
  my $compact = 0;

  push @page, $q->start_div({-class => 'surveyResults', -id => $sid});
  push @page, $q->h2($survey->{'description'});
  push @page, $q->p('Total responses collected: ', $res->{'g_total'}) unless $compact;

  foreach my $k ( sort keys %{$survey->{'question'}} ) {
    # If we come across a comment-type question, we store it's number
    # in a list and skip forward
    (push @comments, $k) && last if $survey->{'question'}->{$k}->{'type'} =~ /text|comment/;

    push @page, $q->h4($k.'.',$survey->{'question'}->{$k}->{'text'});
    push @page, $q->start_table({-class=>'results'});
    push @page, $q->Tr({ -class=>'head' }, th('Answers'),
                       th({-class=>'thRepl'},'Replies'),
                       th({-class=>'thPct'},'%% total'),
                       th({-class=>'thGraph'},'')) unless $compact;
    my $ans = $survey->{'question'}->{$k}->{'answer'};
    my $rep = $res->{'resp'}->{$k}->{'a'};

    foreach my $a (sort keys %{$ans}) {
      $p = round( ($rep->{$a} / $res->{'resp'}->{$k}->{'total'} * 100), 2);
      if ($compact) {
	push @page, $q->Tr(td(shortened($res->{'question'}->{$k}->{'answer'}->{$a}->{'content'}, 4)),
                           td({-class=>'graph'}, bar($p)));
      } else {
	push @page, $q->Tr(td($a.'. '.$ans->{$a}->{'content'}),
                           td({-class=>'number'}, $rep->{$a} || '&nbsp;'),
                           td({-class=>'number'}, "${p}%"),
                           td({-class=>'graph'}, bar($p)));
      }
    }

    push @page, $q->Tr(th('Totals'),
                   th({-class=>'number'},$res->{'resp'}->{$k}->{'total'}),
                   th({-class=>'number'},'&nbsp;'),th('')) unless $compact;
    push @page, $q->end_table();
  }
  push @page, $q->end_div();

  if ( scalar @comments > 0 ) {

    # Listing out comment-type replies
    push @page, start_div({-class=>'surveyResults'});
    push @page, h3('Participant comments');

    foreach my $k (@comments) {
      push @page, $q->h4($survey->{'question'}->{$k}->{'text'});
      my $a = $res->{'resp'}->{$k}->{'a'};
      my @li;
      map { push @li, $q->li(reformat($_)) } sort keys %{$a};
      push @page, $q->ul({-class=>'comments'}, @li);
    }
    push @page, $q->end_div();
  }

  return @page;
}

# Function: reformat(TXT)
#
# Poor-man's wiki engine.  Supported formatting:
#
#   - *bold* and _italics_
#   - single line break is treated as <br/>
#   - double line break creates a <p/>
#   - three spaces, followed by a minus (-) or an asterics (*) and a space create an <ul/>
#   - three spaces, followed by a number, followed by a dot and a space create an <ol/>
#   - list nesting is NOT supported
sub reformat($) {
  debug_trace('info','Entering reformat');
  my $txt = shift;
  my @blocks = split qr%\\n\\n%, $txt;
  my @rtxt;
  foreach my $block (@blocks) {
    next if $block =~ /^$/;
    $block =~ s%\*([^ *][^*]+)\*%<strong>$1</strong>%g;
    $block =~ s%_([^_]+)_%<em>$1</em>%g;
    if ($block =~ /^\s{3}([-*]|\d+\.)\s/) {
      my $tag = ( $1 =~ /\d/ ? 'ol' : 'ul' );
      my $re = ( $tag eq 'ul' ? qr{[-*]} : qr{\d+\.} );
      my $tmp;
      map { $tmp .= "<li>$_</li>" unless $_ eq ''; } split qr%\s{3}$re\s%, $block;
      $block = "\n<$tag>$tmp</$tag>\n";
      $block =~ s%\\n%<br/>%g;
    } else {
      $block =~ s%\\n%<br/>%g;
      $block = "<p>$block</p>";
    }
    push @rtxt, $block;
  }
  return join "\n",@rtxt;
}

# draw a bar
sub bar($) {
  debug_trace('info','Entering bar');
  my $width = shift;
  my $str = '&nbsp;';
  $width = $width * 3;  # arbitrary number, to make graph look better...
  return $q->div( {-class=>'bargraph'},
                  span({-class=>'bar',-style=>"width:${width}px;"},$str) );
}

# shorten text
sub shortened ($$) {
  debug_trace('info','Entering shortened ');
  my($s,$l) = @_;
  return substr($s,1,$l).'&helip;';
}

# Function form_extras
sub form_extras($) {
  debug_trace('info','Entering form_extras');
  my $sid = shift;
  my $js = "Form.getElements('$sid').each(function(s) { s.checked = false; });";
  print $q->script($js);
  return;
}

# Function: round
# Round a floating number to given number of decimals
#
# Parameters:
# $number - Floating number to round
# $precision - Number of decimal places to round to
#
# Caveats:
#
# Perl does not have a real rounding function.  One has to use build
# one's own.  This one is not particularly smart, for instance:
#
# round(12.30123, 2) - will return 12.3, not 12.30.
#
# round(-12.345, 1)  - will return -12.2, *not -12.3* as expected.
#
# The latter one mattaers little to us in our case, as we aren't
# planning to operate negative fractional numbers in survey counts :)
# The former is nuisance...
#
sub round($) {
  debug_trace('info','Entering round');
    my($number) = shift;
    my($precision) = shift;
    return int($number*10**$precision + .5) / 10**$precision;
}


# Function: wiki_format_msg()
#
# Returns a short wiki-like formatting message
sub wiki_format_msg () {
  debug_trace('info','Entering wiki_format_msg ');
  return <<"EOF";
HTML tags will be removed, but you can mark up <strong>*bold*</strong> and
<em>_italics_</em>.  Blank lines separate paragraphs.  A blank line followed
by a line starting with 3 spaces, a minus and a space creates a bullet point.
Same, but with a digit, follwed by a dot instead of a minus will create
numbered list.
EOF
}



# Function show_documentation
#
# Self-documenting application this is no longer
sub show_documentation () {
  debug_trace('info','Entering show_documentation ');
  print standard_headers('Survey Application Documentation');
  open (DOC, 'surveys_doc.html') or die "Unable to open documentation file: $!\n";
  my @doc = <DOC>;
  print @doc;
  print $q->end_html;
  close (DOC);
}

# shut down gracefully
sub graceful_shutdown () {
  debug_trace('info','Entering graceful_shutdown ');
  print $q->div(@pgdebug) if $debug;
  my $end = (times)[0];
  printf "<br/>Elapsed time: %.2f seconds!\n", $end - $start if $debug;
  print $q->end_html;
  exit;
}


# finish it
print $q->div(@pgdebug) if $debug;
my $end = (times)[0];
printf "<br/>Elapsed time: %.2f seconds!\n", ($end - $start) if $debug;
1;

__DATA__

